"""Telegram bot commands."""

import re
import os
import logging
import utils
from datetime import datetime
from dotenv import load_dotenv

from pocketbase import PocketBase, utils as pbutils

from telegram import ReplyKeyboardRemove, ForceReply, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

USE_CODE, PROCESS_CODE = range(2)
(
    SUBSCRIBE_TO_ALERT,
    SUBSCRIBE_TO_ALERT_QUERY,
    SUBSCRIBE_TO_ALERT_FROM_PRICE,
    SUBSCRIBE_TO_ALERT_TO_PRICE,
    SUBSCRIBE_TO_ALERT_CONFIRMATION,
) = range(5)

load_dotenv()

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

client = PocketBase(os.getenv("POCKETBASE_URL"))
print(client)


def create_alert(query, from_price, to_price, created_by):

    expiryDate = utils.get_alert_expiry()
    nextTimeToRun = utils.get_alert_next_time_to_run()
    print(expiryDate, "is the expiry")
    apiKey = query + "_" + expiryDate.strftime("%d/%m/%Y_%H:%M:%S")
    cleanedApiKey = re.sub(r"[^\w\s]", "", apiKey)
    cleanedApiKey = re.sub(r"\s+", "-", cleanedApiKey)
    client.collection("alerts").create(
        {
            "query": query,
            "from_price": from_price,
            "to_price": to_price,
            "expire_at": expiryDate.isoformat(),
            "api_key": apiKey,
            "status": "ready_to_search",
            "next_time_to_run": nextTimeToRun.isoformat(),
            "created_by": created_by,
            "is_first_scrape": True,
        }
    )

    return True


def get_chat_id_by_user_id(user_id):
    print("get_chat_id_by_user_id")
    print(client.collection("chats").get_full_list())
    chats = client.collection("chats").get_list(
        1, 1, query_params={"filter": f'user_id = "{str(user_id)}"'}
    )

    if chats.items is None or len(chats.items) == 0:
        return client.collection("chats").create({"user_id": str(user_id)}).id

    return chats.items[0].id


async def get_user_alert_amt_available(user_id: str):
    chat_id = get_chat_id_by_user_id(user_id)

    codes = client.collection("codes").get_full_list(
        query_params={"filter": f'subscribed_by = "{chat_id}"'}
    )

    total_alerts = 0
    for code in codes:
        total_alerts += code.alert_amt_to_give

    alerts = client.collection("alerts").get_full_list(
        query_params={"filter": f'created_by = "{chat_id}"'}
    )

    return total_alerts - len(alerts)


async def show_start_docs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    print(update.effective_user.id)
    user = update.effective_user
    await update.message.reply_html(
        rf"""
        Hi {user.mention_html()}!

Welcome to Speedy Alert BETA! Use this bot to subscribe to alerts for new listing on Carousell. 🤖🤖

Please send the following command:

<b>Code 🎁</b>
/use_code - Use code to get more alerts for yourself
/request_for_code - Request for more code

<b>Alerts ⚠️</b>
/subscribe_alert - Subscribe to a search query to be alerted
/my_alerts - See the status of your alerts
/check_alerts_left - Check how many alerts you are left with


------------------------
Take note that each subscription alert will last for 1 month! You will need to renew after to get more results.

If you have any questions or feedback, please fill in this form to reach us! ⚡⚡
    """,
        reply_markup=ForceReply(selective=True),
    )


async def show_help_docs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    await update.message.reply_html(
        r"""
Help is here! 🤖🤖

Please send the following command:

<b>Code 🎁</b>
/use_code - Use code to get more alerts for yourself
/request_for_code - Request for more code

<b>Alerts ⚠️</b>
/subscribe_alert - Subscribe to a search query to be alerted
/my_alerts - See the status of your alerts
/check_alerts_left - Check how many alerts you are left with


------------------------
Take note that each subscription alert will last for 1 month! You will need to renew after to get more results.

If you have any questions or feedback, please fill in this form to reach us! ⚡⚡
    """,
        reply_markup=ForceReply(selective=True),
    )


async def use_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    print("use_code")
    await update.message.reply_html(
        r"""
Hi! Please type in your code to redeem your alerts! 🤖🤖

Type /cancel to cancel this process.
    """,
        reply_markup=ForceReply(selective=True),
    )

    return PROCESS_CODE


async def use_code_process(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    print("use_code_process")
    code = update.message.text
    message = ""
    is_error = False

    try:
        user_id = update.effective_user.id
        if user_id is None:
            raise Exception("Something went wrong with your chat.")

        codes = client.collection("codes").get_list(
            1, 1, query_params={"filter": f'code = "{code}"'}
        )

        # Check if code exist in db.
        if codes.items is None or len(codes.items) == 0:
            raise Exception("Code is not valid.")

        # Check if code is used.
        if codes.items[0].subscribed_by is not None:
            raise Exception("Code is already used.")

        chat_id = get_chat_id_by_user_id(user_id)

        # Update code to be used.
        client.collection("codes").update(codes.items[0].id, {"subscribed_by": chat_id})

        message = codes.items[0].alert_amt_to_give
    except pbutils.ClientResponseError as e:
        is_error = True
        message = e.data["message"]

    except Exception as e:
        is_error = True
        message = str(e)

    if is_error:
        await update.message.reply_text(
            f"{message} Please try again from the start!",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        await update.message.reply_html(
            f"Code is valid! You have successfully redeemed <b> {message} </b> new \
                alerts your code! 🎉🎉",
            reply_markup=ReplyKeyboardRemove(),
        )

    return ConversationHandler.END


async def subscribe_to_alert(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    print("subscribe_to_alert")
    user_id = update.effective_user.id

    alerts_left = await get_user_alert_amt_available(user_id)

    if alerts_left == 0:
        await update.message.reply_text(
            "You have no alerts left! Please use a code \
            to get more alerts!"
        )
        return ConversationHandler.END

    await update.message.reply_html(
        rf"""
        You have <b>{alerts_left}</b> alerts left!

Hi! Time to subscribe to an alert! 🤖🤖

First, please enter the <b>search query</b> you want to subscribe to.

Type /cancel to cancel this process.
    """,
        reply_markup=ForceReply(selective=True),
    )

    return SUBSCRIBE_TO_ALERT_QUERY


async def subscribe_to_alert_query(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    print("subscribe_to_alert_query")
    query = update.message.text

    if query is None or query.strip() == "":
        await update.message.reply_text("Please enter a valid query.")
        return SUBSCRIBE_TO_ALERT_QUERY

    context.user_data["query"] = query

    await update.message.reply_html(
        rf"""
Great! You will be alerted for <b>{query}</b>!

Now, please enter the <b>minimum price</b> you want to be alerted at. Please send 0 if you do not want to set a minimum\
    price.

⚠️ However, setting a minimum price is strongly encourage to lessen spam.

Type /cancel to cancel and restart this process.
"""
    )

    return SUBSCRIBE_TO_ALERT_FROM_PRICE


async def subscribe_to_alert_from_price(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    print("subscribe_to_alert_from_price")
    from_price = update.message.text
    if from_price.isdecimal() is False:
        await update.message.reply_text("Please enter a valid price.")
        return SUBSCRIBE_TO_ALERT_FROM_PRICE

    context.user_data["from_price"] = from_price

    await update.message.reply_html(
        rf"""
    Great! You will be alerted for the minimum price of <b>${from_price}</b>!
Now, please enter the <b>maximum price</b> you want to be alerted at. Please send 0 if you do not want to set a maximum\
    price.
    """
    )

    return SUBSCRIBE_TO_ALERT_TO_PRICE


async def subscribe_to_alert_to_price(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    print("subscribe_to_alert_to_price")
    to_price = update.message.text
    if to_price.isdecimal() is False:
        await update.message.reply_text("Please enter a valid price.")
        return SUBSCRIBE_TO_ALERT_TO_PRICE

    context.user_data["to_price"] = to_price

    await update.message.reply_html(
        rf"""
    Great! You will be alerted for the maximum price of <b>${to_price}</b>!
    """
    )

    await update.message.reply_html(
        rf"""
        Here is your alert subscription details:
        Search Query: <b>{context.user_data['query']}</b>
        Minimum Price: <b>{'-' if context.user_data['from_price'] == '0' else f'${context.user_data["from_price"]}'}</b>
        Maximum Price: <b>{'-' if context.user_data['to_price'] == '0' else f'${context.user_data["to_price"]}'}</b>

Please reply with <b>confirm</b> to confirm your subscription. Type /cancel to cancel and restart this process.
        """
    )

    return SUBSCRIBE_TO_ALERT_CONFIRMATION


async def subscribe_to_alert_confirmation(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    print("subscribe_to_alert_confirmation")
    try:
        confirmation = update.message.text
        if confirmation.lower() != "confirm":
            await update.message.reply_text(
                "Please enter confirm to confirm your\
                subscription,\ otherwise type /cancel to \
                    cancel and restart this process."
            )
            return SUBSCRIBE_TO_ALERT_CONFIRMATION

        query = context.user_data["query"]
        from_price = (
            None
            if context.user_data["from_price"] == "0"
            else float(context.user_data["from_price"])
        )
        to_price = (
            None
            if context.user_data["to_price"] == "0"
            else float(context.user_data["to_price"])
        )

        chat_id = get_chat_id_by_user_id(update.effective_user.id)

        print(query, from_price, to_price, chat_id)
        result = create_alert(query, from_price, to_price, chat_id)

        if result:
            await update.message.reply_html(
                """You have successfully subscribed to your alert! 🎉🎉

Please take note that the alert will only be sent to you when there is a new listing that matches your search query and\
    price range.

You will be receiving alerts soon!

You can view your alerts by typing /my_alerts.
                """
            )
        else:
            await update.message.reply_text(
                "There was an error creating your alert.\
                Please try again later."
            )

    except pbutils.ClientResponseError as e:
        await update.message.reply_text(
            f"There was an error creating your alert.\
            Please try again later. {e.data.message}"
        )
    except Exception as e:
        print(e)
        await update.message.reply_text(
            f"There was an error creating your alert.\
            Please try again later. {e}"
        )
    finally:
        return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    print("cancel")
    await update.message.reply_text(
        "Bye! I hope we can talk again some day.", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


async def see_my_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    print("see_my_alerts")
    try:
        user_id = update.effective_user.id
        chat_id = get_chat_id_by_user_id(user_id)

        alerts = client.collection("alerts").get_full_list(
            query_params={"filter": f'created_by = "{str(chat_id)}"'}
        )

        message = ""
        chat_num = 1

        for alert in alerts:
            listings = client.collection("listings").get_full_list(
                query_params={"filter": f'alert_id = "{alert.id}"'}
            )
            message += f"""
Alert {chat_num}.\n<b>Search Query:</b> {alert.query}\n"""
            if alert.from_price != 0:
                message += f"""<b>Minimum Price:</b> ${alert.from_price}\n"""
            if alert.to_price != 0:
                message += f"""<b>Maximum Price:</b> ${alert.to_price}\n"""

            expiry = datetime.fromisoformat(alert.expire_at)
            expiry.strftime("%I:%M %p")
            message += f'<b>Expire At:</b> {expiry.strftime("%d %b %y, %I:%M %p")}\n'
            message += f"<b>Listing Found:</b> {len(listings)}\n"

            message += "\n"
            chat_num += 1

        if chat_num == 1:
            await update.message.reply_html(
                "You do not have any alerts subscribed to you! :("
            )
        else:

            await update.message.reply_html(
                f"""Here are your alerts: 
                {message}"""
            )
    except Exception as e:
        await update.message.reply_text(
            f"Sorry, something went wrong. Please try again later. {e}"
        )
        print(e)


async def check_alerts_left(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    print("check_alerts_left")
    user_id = update.effective_user.id
    message = ""
    is_error = False

    try:
        message = await get_user_alert_amt_available(user_id)

    except pbutils.ClientResponseError as e:
        is_error = True
        message = e.data["message"]

    except Exception as e:
        print('error')
        is_error = True
        message = str(e)

    if is_error:
        await update.message.reply_text(
            f"{message} Please try again!", reply_markup=ReplyKeyboardRemove()
        )
    else:
        await update.message.reply_html(
            f"""You have <b> {message} </b> alerts left!
            """,
            reply_markup=ReplyKeyboardRemove(),
        )


async def request_for_code(update: Update) -> None:
    print("get_codes")
    await update.message.reply_html(
        """
Hi there! 👋👋

Thank you for your interest in using this bot, we are currently in beta and are only giving out codes to a selected few\
    . If you are interested, please fill in this form and we will get back to you as soon as possible!
    """,
        reply_markup=ForceReply(selective=True),
    )


if __name__ == "__main__":
    print("initiating bot")

    # botApp = Application.builder().token(
    #     "6104332010:AAF3Se2eVd_7u2lIBqjCNgjOJRGw0p_x1n8").build()
    client = PocketBase(os.getenv("POCKETBASE_URL"))
    botApp = Application.builder().token(os.getenv("TELEGRAM_TOKEN")).build()

    use_code_handler = ConversationHandler(
        entry_points=[CommandHandler("use_code", use_code)],
        states={
            PROCESS_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, use_code_process)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    subscribe_to_alert_handler = ConversationHandler(
        entry_points=[CommandHandler("subscribe_alert", subscribe_to_alert)],
        states={
            SUBSCRIBE_TO_ALERT_QUERY: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, subscribe_to_alert_query
                )
            ],
            SUBSCRIBE_TO_ALERT_FROM_PRICE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, subscribe_to_alert_from_price
                )
            ],
            SUBSCRIBE_TO_ALERT_TO_PRICE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, subscribe_to_alert_to_price
                )
            ],
            SUBSCRIBE_TO_ALERT_CONFIRMATION: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, subscribe_to_alert_confirmation
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    botApp.add_handler(CommandHandler("start", show_start_docs))
    botApp.add_handler(CommandHandler("help", show_help_docs))
    botApp.add_handler(CommandHandler("request_for_code", request_for_code))
    botApp.add_handler(CommandHandler("my_alerts", see_my_alerts))

    botApp.add_handler(CommandHandler("check_alerts_left", check_alerts_left))
    botApp.add_handler(use_code_handler)
    botApp.add_handler(subscribe_to_alert_handler)

    botApp.run_polling()
