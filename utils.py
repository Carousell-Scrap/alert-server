from datetime import datetime
from dateutil.relativedelta import relativedelta
import string
import random


def get_alert_next_time_to_run(seconds=300):
    return datetime.today() + relativedelta(seconds=seconds)


def get_alert_expiry(days=30):
    return datetime.today() + relativedelta(days=days)


def generate_random_string(length=5):
    characters = (
        string.ascii_letters + string.digits
    )  # You can customize the character set as needed
    random_string = "".join(random.choice(characters) for _ in range(length))
    return random_string
