from datetime import datetime
from dateutil.relativedelta import relativedelta
import string
import random


def get_alert_next_time_to_run(min_seconds=150, max_seconds=600):
    seconds = random.randint(min_seconds, max_seconds)
    return datetime.today() + relativedelta(seconds=seconds)


def get_alert_expiry(days=30):
    return datetime.today() + relativedelta(days=days)


def generate_random_string(length=5):
    characters = (
        string.ascii_letters + string.digits
    )  # You can customize the character set as needed
    random_string = "".join(random.choice(characters) for _ in range(length))
    return random_string
