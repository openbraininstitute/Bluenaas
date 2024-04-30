'''Common settings for the app.'''
import logging
import os

L = logging.getLogger()

L.setLevel(logging.DEBUG)

ALLOWED_ORIGIN = os.getenv('ALLOWED_ORIGIN', 'http://localhost:8080')
ALLOWED_IP = os.getenv('ALLOWED_IP', '')
