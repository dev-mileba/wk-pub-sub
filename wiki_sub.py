import datetime
import os
import json
from google.cloud import pubsub_v1
import streamlit as st

from dotenv import load_dotenv
load_dotenv()
publisher_client = pubsub_v1.PublisherClient()
subscriber_client = pubsub_v1.SubscriberClient()

project_id = 'eduimpact-504119'
project_topic = 'wiki-topic'
project_subscription = 'wiki-topic-sub'

subscription_path = subscriber_client.subscription_path(project_id, project_subscription)

#Ensure that the Pub/Sub exist
def ensure_subscription_exists():
    try:
        subscriber_client.get_subscription(subscription=subscription_path)
        print(f"Subscription '{project_subscription}' already exist")
    except Exception as e:
        print(f"Subscription '{project_subscription}' does not exist. creating it now...")
        topic_path = publisher_client.topic_path(project_id, project_topic)
        subscriber_client.create_subscription(name=subscription_path, topic=project_topic)
        print(f"Subscription '{project_subscription}' created successfully")

#Callback function to process incoming Pub/Sub messages
def callback(message):
    transformed_message = transform_message(message)
    print(json.dumps(transformed_message))
    message.ack() #Acknowledge the message

def transform_message(message):
    event = json.loads(message.data.decode('utf-8'))
    length = event.get("length") or {}
    old_len, new_len = length.get("old", 0), length.get("new", 0)
    byte_change = new_len - old_len if old_len and new_len else None

    return {
        "id": event.get("id"),
        "type": event.get("type"),
        "wiki": event.get("wiki"),
        "domain": event.get("domain"),
        "namespace": event.get("namespace"),
        "title": event.get("title"),
        "user": event.get("user"),
        "bot": event.get("bot"),
        "minor": event.get("minor"),
        "comment": event.get("comment"),
        "byte_change": byte_change,
        "old_revision": event.get("revision", {}).get("old"),
        "new_revision": event.get("revision", {}).get("new"),
        "timestamp": datetime.datetime.fromtimestamp(event.get("timestamp",0)).isoformat(),
        "url": event.get("title_url")
    }

# Simple Streamlit app to display the message in real-time
st.title("Real-time Wikipedia Changes")

# A card that shows the count of messages recieved
message_count_card = st.empty()
message_count = 0

# A card that displays the latest message
message_card = st.empty()
message_card.markdown("Waiting for messages...")


if 'message_count' not in st.session_state:
    st.session_state['message_count'] = 0

# Send to MongoDB as Document
# Send to BigQuery

if __name__ == "__main__":
    ensure_subscription_exists()
    streaming_pull_future = subscriber_client.subscribe(subscription_path, callback=callback)
    print(f"Listening for messages on {subscription_path}")


    try:
        streaming_pull_future.result()
    except KeyboardInterrupt:
        streaming_pull_future.cancel()
        streaming_pull_future.result()
