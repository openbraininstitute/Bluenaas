'''Common settings for the app.'''
import logging
import os

L = logging.getLogger()

DEBUG = os.getenv('DEBUG') is not None
if DEBUG:
    L.setLevel(logging.DEBUG)
else:
    L.setLevel(logging.INFO)

ALLOWED_ORIGIN = os.getenv('ALLOWED_ORIGIN', 'http://localhost:8080')
ALLOWED_IP = os.getenv('ALLOWED_IP', '')
