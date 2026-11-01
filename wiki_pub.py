# Wiki publisher

# It would connect to the endpoint of the wiki to get data
# It publishes the data to the pub/sub topic for further processing

import requests
import json
import time
import os
from dotenv import load_dotenv
from google.cloud import pubsub_v1

load_dotenv()



STREAM_URL = 'https://stream.wikimedia.org/v2/stream/recentchange'



#Step 1: create your client

client = pubsub_v1.PublisherClient()
project_id = os.getenv("PROJECT_ID")
project_topic = os.getenv("PROJECT_TOPIC")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}

#Step 2: Establish a connection to the endpoint
def iter_events(session: requests.Session):
    backoff =1
    while True:
        try: #Connecting to the stream
            with session.get(STREAM_URL, headers=HEADERS, stream=True, timeout=30) as response:
                response.raise_for_status() #Checking the server's response
                for raw_line in response.iter_lines(decode_unicode=True):#Reading the data
                    if raw_line is None or not raw_line.startswith('data: '):
                        continue
                    payload = raw_line[len('data: '):]
                    try:
                        yield json.loads(payload)
                    except json.JSONDecodeError:#Handling errors
                        continue
        except (requests.RequestException, ConnectionError) as e:
            print(f"Error occurred: {e}. Retrying in {backoff} seconds ... ")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)



#Publish an event to a Google Cloud Pub/Sub Topic
def publish_to_pubsub(event):
    try:
        data = json.dumps(event).encode('utf-8') # Convert the event into JSON text (a universal format), then into bytes, which Pub/Sub requires
        future = client.publish(f'projects/{project_id}/topics/{project_topic}', data) # Send the bytes to the topic's "address" and get back a "future" (a claim ticket for the result)
        print(f"Published message ID: {future.result()}")
    except Exception as e:
        print(f'Failed to publish message: {e}')



# Call the function
if __name__ == '__main__':
    with requests.Session() as session:
        for event in iter_events(session):
            publish_to_pubsub(event)