"""Flask app for the Carousell Scalper API."""

import re
import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from dateutil.relativedelta import relativedelta

from flask import request, jsonify, Flask
from pocketbase import PocketBase, utils as pbutils
from workers.carousell_scalper_worker_ph import (
    scrape_carousell_with_params,
    scrape_ready_alerts,
)

load_dotenv()

# Enable logging.
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

client = PocketBase(os.getenv("POCKETBASE_URL"))


app = Flask(__name__)


@app.route("/ss")
def ss():
    scrape_ready_alerts()
    return jsonify({"ok": "ok"}), 200


@app.route("/scrape-carousell")
def scrape_carousell():
    """Scrape carousell,

    Returns:
        JSON: Return statement to api.
    """
    try:
        alerts_to_scrape = client.collection("alerts").get_full_list(
            query_params={
                "filter": f"""status = "ready_to_search" &&
                                        next_time_to_run < "{datetime.today()}" &&
                                        expire_at > "{datetime.today()}" """
            }
        )

        for alert in alerts_to_scrape:
            print(alert.id)
            user_id = (
                client.collection("chats")
                .get_list(1, 1, query_params={"filter": f'id = "{alert.created_by}"'})
                .items[0]
                .user_id
            )

            if user_id is None:
                continue
            print(user_id)
            print(alert.query, alert.from_price, alert.to_price)

            result = scrape_carousell_with_params.delay(
                alert.query, alert.id, user_id, alert.from_price, alert.to_price
            )
            print(result)

    except pbutils.ClientResponseError as error:
        return (
            jsonify({"status": "not ok", "message": error.data["message"]}),
            error.status,
        )

    return jsonify({"ok": "ok"}), 200


@app.route("/make-alert-request", methods=["POST"])
def register_client_alert_request():
    """Register new subscription for alert.

    Returns:
        JSON: result of request.
    """
    try:
        print("register_client_alert_request")
        query = request.form["query"]

        from_price = None
        if "from_price" in request.form:
            from_price = request.form["from_price"]

        to_price = None
        if "to_price" in request.form:
            to_price = request.form["to_price"]

        expiry_date = datetime.today() + relativedelta(months=1)
        next_time_to_run = datetime.today() + relativedelta(minutes=10)
        print(expiry_date, "is the expiry")
        api_key = query + "_" + expiry_date.strftime("%d/%m/%Y_%H:%M:%S")
        cleaned_api_key = re.sub(r"[^\w\s]", "", api_key)
        cleaned_api_key = re.sub(r"\s+", "-", cleaned_api_key)
        client.collection("alerts").create(
            {
                "query": query,
                "from_price": from_price,
                "to_price": to_price,
                "expire_at": expiry_date.isoformat(),
                "api_key": api_key,
                "status": "ready_to_search",
                "next_time_to_run": next_time_to_run.isoformat(),
            }
        )

        return (
            jsonify(
                {"status": "ok", "api_key": cleaned_api_key, "expiry_data": expiry_date}
            ),
            200,
        )
    except pbutils.ClientResponseError as error:
        return jsonify({"status": "not ok", "message": error.data}), error.status
    except Exception as error:
        return jsonify({"status": "not ok", "message": error})


@app.route("/")
def index():
    """Nothing much here yet.

    Returns:
        JSON: results to be return to request.
    """
    print("index")
    return jsonify({"ok": "ok"}), 200


if __name__ == "__main__":
    print("initiating app")
    app.run(debug=True)
