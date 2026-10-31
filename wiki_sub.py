import os
import json
from google.cloud import pubsub_v1

from dotenv import load_dotenv

publisher_client = pubsub_v1.PublisherClient()
subscriber_client = pubsub_v1.SubscriberClient()

project_id = 'eduimpact-504119'
project_topic = 'wiki-topic'
project_subscription = 'wiki-topic-sub'

