from datetime import datetime
from dateutil.relativedelta import relativedelta


def get_alert_next_time_to_run(minutes=3):
    # return datetime.today() + relativedelta(seconds=20)
    return datetime.today() + relativedelta(minutes=minutes)


def get_alert_expiry(days=30):
    return datetime.today() + relativedelta(days=days)
