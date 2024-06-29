from datetime import datetime
from dateutil.relativedelta import relativedelta
import random


def get_alert_next_time_to_run(seconds=20):
    # Next time around 3min 20sec to 5min.
    return datetime.today() + relativedelta(second=random.randint(10, seconds))


def get_alert_expiry(days=30):
    return datetime.today() + relativedelta(days=days)
