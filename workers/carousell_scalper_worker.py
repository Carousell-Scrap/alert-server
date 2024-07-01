"""Worker file for scrapping."""

import re
import os
import time
from urllib.parse import quote
from datetime import datetime, date
from urllib.parse import urlparse

import asyncio
from celery import Celery
from telegram import Bot

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from selenium import webdriver
from pocketbase import PocketBase, utils as pbutils

import utils
from constants import USER_AGENTS, BASE_URL, CURRENCY_MAP
import random


def init_celery():
    """Init Celery.
    Returns:
        celery: Celery instance.
    """
    print("init")
    # Initialize Celery.
    celery_init = Celery(
        "workers.carousell_scalper_worker",
        broker=os.getenv("CELERY_BROKER_URL"),
        backend=os.getenv("CELERY_RESULT_BACKEND"),
    )

    celery_init.conf.beat_schedule = {
        "scrape_ready_alerts": {
            "task": "workers.carousell_scalper_worker.scrape_ready_alerts",
            "schedule": 90.0,
        }
    }

    return celery_init


load_dotenv()

celery = init_celery()


def get_client():
    return PocketBase(os.getenv("POCKETBASE_URL"))


@celery.task()
def scrape_carousell_with_params(
    alert_id,
    chat_id,
    query=None,
    from_range=None,
    to_range=None,
    is_first_time=False,
    initial_url=None,
):
    """Scrape Carousell website with search params. Will update DB when done.

    Args:
        query (string): search query.
        alert_id (string): alert id as per db in alerts.
        chat_id (string): chat id as per db in chats
        from_range (float, optional): Minimum price. Defaults to None.
        to_range (float, optional): Maximum price. Defaults to None.
        is_first_time (bool, optional): Is this the first time the alert runs.
        Defaults to False.
    """
    print("data")
    print(initial_url)
    print(query, from_range, to_range)

    try:
        print(f"set status to ongoing... [{alert_id}]")
        get_client().collection("alerts").update(
            alert_id,
            {
                "status": "ongoing",
            },
        )

        print("setting up url...")
        if initial_url is None or initial_url == "":
            url = set_up_scape_url(query, from_range, to_range)
        else:
            url = initial_url
        print(url)

        print("setting up driver...")
        driver = set_up_driver_option(random.choice(USER_AGENTS))
        driver.get(url)

        # ! Remove this as we only need the most recent.
        # Click on load more button until there is no more.
        if is_first_time:
            print("Is first time loading longer...")
            continuous_press_load_more_button(driver, 5)

        print("scrapping...")
        soup = BeautifulSoup(driver.page_source, "html.parser")
        items = scrape_page(soup, alert_id, hostname=urlparse(url).hostname)

        items_created, messages = create_listing_to_db(
            items, alert_id, hostname=urlparse(url).hostname
        )

        print("sending messages...")

        if is_first_time:
            messages = [
                f"Alert ran for the first time and found {items_created} new listings! Subsequent alerts will only send\
 you new listings.\n"
            ]

            asyncio.run(
                send_messages(
                    chat_id,
                    messages,
                    query=query,
                    from_range=from_range,
                    to_range=to_range,
                    initial_url=initial_url,
                )
            )
        else:
            if items_created > 0:
                asyncio.run(
                    send_messages(
                        chat_id,
                        messages,
                        query=query,
                        from_range=from_range,
                        to_range=to_range,
                        initial_url=initial_url,
                    )
                )

        print("updating alert...")
        next_time_to_run = utils.get_alert_next_time_to_run()
        get_client().collection("alerts").update(
            alert_id,
            {
                "status": "ready_to_search",
                "next_time_to_run": next_time_to_run.isoformat(),
                "is_first_scrape": False,
            },
        )

        print(f"{items_created} new listings created... [{alert_id}]")

    except pbutils.ClientResponseError as error:
        print(f"Seem to be an error with pocketbase... {error.data}")
    except Exception as error:
        print(f"Seem to be an error... {error}")
    finally:
        print("quitting driver...")
        driver.delete_all_cookies()
        driver.quit()
        get_client().collection("alerts").update(
            alert_id,
            {
                "status": "ready_to_search",
            },
        )


@celery.task()
def scrape_ready_alerts():
    """Called by celery beat to scrape alerts that are ready to be scraped. Should
    be running every x seconds.
    """
    try:
        print("scrape_ready_alerts")

        alerts_to_scrape = get_client().collection("alerts").get_full_list(
            query_params={
                "filter": f"""status = "ready_to_search" &&
                                        next_time_to_run < "{datetime.today()}" &&
                                        expire_at > "{datetime.today()}" """
            }
        )

        for alert in alerts_to_scrape:
            user_id = (
                get_client().collection("chats")
                .get_list(1, 1, query_params={"filter": f'id = "{alert.created_by}"'})
                .items[0]
                .user_id
            )
            if user_id is None:
                continue

            print("scrape_carousell_with_params.delay")
            print(alert.url)
            if alert.url is not None:
                scrape_carousell_with_params.delay(
                    alert.id,
                    user_id,
                    initial_url=alert.url,
                    is_first_time=alert.is_first_scrape,
                )
            else:
                scrape_carousell_with_params.delay(
                    alert.id,
                    user_id,
                    query=alert.query,
                    from_range=alert.from_price,
                    to_range=alert.to_price,
                    is_first_time=alert.is_first_scrape,
                )
    except pbutils.ClientResponseError as error:
        print(error.data)
    except Exception as error:
        print(error)


def scrape_page(
    soup: BeautifulSoup, alert_id: str, hostname: str = "https://www.carousell.sg"
):
    """Scrape the page for items. Page should be loaded in soup using a webdriver.

    Args:
        soup (BeautifulSoup): Used to scape elements in page, page should be loaded.
        alert_id (str): alert id as per db in alerts.

    Returns:
        _type_: items found.
    """
    print("scrape_page")

    # Need to change when the classname changes.soup
    item_listings = soup.find_all("div", {"data-testid": re.compile("listing-card-")})

    items_found = []
    for item_listing in item_listings:
        # seller
        seller = item_listing.find(
            "p", {"data-testid": "listing-card-text-seller-name"}
        ).getText()

        # price
        price_result = item_listing.find(
            "p",
            {
                "title": re.compile(
                    CURRENCY_MAP[hostname.split(".")[len(hostname.split(".")) - 1]]
                )
            },
        )
        price = price_result.getText() if price_result else "0"

        # name
        name = item_listing.find("p", {"style": re.compile("--max-line")}).getText()

        item_id = item_listing["data-testid"].split("-")[2]
        urlify_name = name
        urlify_name = re.sub(r"[^\w\s]", "", urlify_name)
        urlify_name = re.sub(r"\s+", "-", urlify_name)
        if urlify_name[0] == "-":
            urlify_name = urlify_name[1:]
        if urlify_name[-1] == "-":
            urlify_name = urlify_name[:-1]
        item_url = f"{hostname}/p/{urlify_name}-{item_id}"
        clean_price = price.replace("$", "").replace(",", "")
        clean_price = re.sub(r"[a-zA-Z]", r"", clean_price).strip()

        items_found.append(
            {
                "listing_id": item_id,
                "detail_url": item_url,
                "image_url": item_listing.find_all("img")[0].get("src"),
                "name": name,
                "price": float(clean_price),
                "seller": seller,
                "date_found": date.today().isoformat(),
                "alert_id": alert_id,
            }
        )

    return items_found


def set_up_scape_url(query: str, from_range: float, to_range: float):
    """Set up scrape url for selenium to load.

    Args:
        query (str): Search query to search.
        from_range (float): Filter for the minimum price.
        to_range (float): Filter for the maximum price.

    Returns:
        _type_: Url to be used to scrape.
    """
    filters = []
    if from_range is not None:
        filters.append(f"price_start={from_range}")

    if to_range is not None and to_range != 0:
        filters.append(f"price_end={to_range}")

    url = f"{BASE_URL}/search/{quote(query)}/?"
    url += f'addRecent=false&sort_by=3&tab=marketplace&includeSuggestions=false{"&" if len(filters) > 0 else ""}'
    url += f'{ ("&".join(filters)) if len(filters) > 0 else ""}'
    return url


async def send_messages(
    chat_id: str,
    messages: list,
    query=None,
    from_range=None,
    to_range=None,
    initial_url=None,
):
    """Send all messages of alert to the user telegram.

    Args:
        chat_id (str): chat id as per db in chats. Use to identify chat user.
        messages (list): List of messages to be sent to user.
        query (str): What is the query used to search.
        from_range (str): What is the minimum price used to search.
        to_range (str): What is the maximum price used to search.
    """
    print("send messages...", initial_url)
    try:
        bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))
        await bot.initialize()

        for message in messages:
            message += "----- ----- -----\n"
            if initial_url is not None:
                message += f"Initial URL: {initial_url}\n"
            else:
                message += f'Query: {query}\n\
Minimum Price: {"-" if from_range== 0 else ("$" + str(from_range))}\n\
Maximum Price: {"-" if to_range== 0 else ("$" + str(to_range))}\n'

            message += "----- ----- -----\n"
            message += "We are constantly improving! \n\
Contact me@buildersjam.com for feedback and enquires! 💯💯\n\n"
            await bot.send_message(
                chat_id, message, parse_mode="html", disable_web_page_preview=True
            )

    finally:
        await bot.shutdown()


def create_listing_to_db(
    items: list, alert_id: str, hostname: str = "https://www.carousell.sg"
):
    """Create listings found to the db.

    Args:
        items (list): List of items to be created.
        alert_id (str): alert id as per db in alerts.

    Returns:
        List: Number of items that are actually created after filtering and messages
        to be sent.
    """
    num_of_items_created = 0
    messages = [""]
    message_index = 0
    print(f"looking through {str(len(items))} items...")
    for item in items:
        listing = get_client().collection("listings").get_list(
            1,
            1,
            query_params={
                "filter": f'listing_id = "{item["listing_id"]}" && alert_id ="{alert_id}"'
            },
        )
        if listing.items is None or len(listing.items) == 0:
            num_of_items_created += 1

            if num_of_items_created % 8 == 0:
                messages.append("")
                message_index += 1

            messages[
                message_index
            ] += f'<b>{item["name"]}</b>\nPrice: <b>{CURRENCY_MAP[hostname.split(".")[len(hostname.split(".")) - 1]]}\
{item["price"]}\
                </b>\nSeller:{item["seller"]}\nVisit Here: {item["detail_url"]}\n\n\n'

            get_client().collection("listings").create(item)

    return num_of_items_created, messages


def set_up_driver_option(user_agent: str):
    """Set up driver options for selenium.

    Args:
        user_agent (str): Used to scrape with user agent.

    Returns:
        WebDriver: Driver to be used to scrape.
    """

    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--enable-javascript")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--remote-debugging-port=9222")
    options.add_argument(f"user-agent={user_agent}")
    # options.add_argument("--remote-debugging-port=9222")
    driver = webdriver.Remote(os.getenv("SELENIUM_URL"), options=options)

    return driver


def continuous_press_load_more_button(driver: webdriver, sleep_time=2.5):
    """
    Ask driver to continuously press load more button until there is no more items to
    load.

    Args:
        driver (webdriver): Webdriver from selenium.
        sleep_time (float, optional): Time to sleep for more button to load. Defaults
        to 2.5.
    """

    try:
        more_button = driver.find_element(
            "xpath", "//button[contains(text(), 'Show more results')]"
        )
    except:  # noqa: E722
        more_button = None

    while more_button is not None:
        try:
            print("loading more...")
            more_button.click()

            time.sleep(sleep_time)

            more_button = driver.find_element(
                "xpath", "//button[contains(text(), 'Show more results')]"
            )
        except:  # noqa: E722
            more_button = None

    print("loading done...")
