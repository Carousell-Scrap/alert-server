from datetime import datetime, date
from dateutil.relativedelta import relativedelta


def get_alert_next_time_to_run(minutes=1):
    return datetime.today() + relativedelta(minutes=minutes)


def get_alert_expiry(days=30):
    return datetime.today() + relativedelta(days=days)
