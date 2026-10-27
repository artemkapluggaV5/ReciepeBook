import logging

class PaymentPrivacyFilter(logging.Filter):
    def filter(self, record):
        if '/payments/' in record.getMessage():
            record.msg = 'Payment endpoint response (request parameters redacted)'
            record.args = ()
        return True
