import datetime
import os

import streamlit as st

import altair as alt
import pandas as pd
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MAX_EVENTS = 20000  # Most recent events loaded from MongoDB per refresh
HUMAN_COLOR, BOT_COLOR = "#2a78d6", "#eb6834"
LOCAL_TZ = datetime.datetime.now().astimezone().tzinfo


@st.cache_resource
def get_collection():
    """
    One MongoDB client per Streamlit server; the subscriber (wiki_sub.py) writes to this collection.
    """
    collection = MongoClient(os.getenv("MONGODB_URI"))["wiki"]["changes"]
    collection.create_index("received_at")
    return collection


def load_events(collection, window_minutes):
    """
    Fetch the events received within the time window, newest first.
    """
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=window_minutes)
    cursor = (
        collection.find({"received_at": {"$gte": cutoff}}, {"_id": 0})
        .sort("received_at", -1)
        .limit(MAX_EVENTS)
    )
    return list(cursor)


def to_dataframe(events):
    df = pd.DataFrame(events)
    # MongoDB returns naive UTC datetimes; convert to local time to match the event timestamps
    df["received_at"] = pd.to_datetime(df["received_at"]).dt.tz_localize("UTC").dt.tz_convert(LOCAL_TZ).dt.tz_localize(None)
    df["bot"] = df["bot"].fillna(False).astype(bool)
    df["editor_type"] = df["bot"].map({True: "Bot", False: "Human"})
    df["byte_change"] = pd.to_numeric(df["byte_change"], errors="coerce")
    df["event_time"] = pd.to_datetime(df["timestamp"], errors="coerce").fillna(df["received_at"])
    return df


def bar_chart(df, field, title, top_n=10):
    counts = df[field].value_counts().head(top_n).rename_axis(field).reset_index(name="edits")
    return (
        alt.Chart(counts, title=title)
        .mark_bar(color=HUMAN_COLOR, cornerRadiusEnd=4)
        .encode(
            x=alt.X("edits:Q", title="Events"),
            y=alt.Y(f"{field}:N", sort="-x", title=None),
            tooltip=[alt.Tooltip(f"{field}:N"), alt.Tooltip("edits:Q", title="Events")],
        )
        .properties(height=30 * len(counts) + 40)
    )


st.set_page_config(page_title="Wikipedia Live Changes", layout="wide")
st.title("Real-time Wikipedia Changes")

collection = get_collection()

# Sidebar filters (changing one reruns the whole app)
with st.sidebar:
    st.header("Filters")
    window_minutes = st.select_slider("Time window (minutes)", options=[1, 5, 15, 30, 60], value=15)
    include_bots = st.toggle("Include bot edits", value=True)
    event_types = st.multiselect(
        "Event types",
        ["edit", "new", "log", "categorize"],
        default=["edit", "new", "log", "categorize"],
    )
    wiki_filter = st.text_input("Wiki contains (e.g. enwiki)", "")
    refresh_seconds = st.select_slider("Refresh every (seconds)", options=[1, 2, 5, 10], value=2)


@st.fragment(run_every=refresh_seconds)
def render_dashboard():
    events = load_events(collection, window_minutes)
    total_received = collection.estimated_document_count()

    if not events:
        st.info("No events in MongoDB for this time window. Is wiki_sub.py running?")
        return

    df = to_dataframe(events)
    now = pd.Timestamp.now()
    df = df[df["received_at"] >= now - pd.Timedelta(minutes=window_minutes)]
    if not include_bots:
        df = df[~df["bot"]]
    if event_types:
        df = df[df["type"].isin(event_types)]
    if wiki_filter:
        df = df[df["wiki"].fillna("").str.contains(wiki_filter, case=False)]

    if df.empty:
        st.warning("No events match the current filters yet.")
        return

    # KPI row
    last_minute = df[df["received_at"] >= now - pd.Timedelta(minutes=1)]
    edits = df[df["type"].isin(["edit", "new"])]
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Events in window", f"{len(df):,}", help=f"{total_received:,} events stored in MongoDB")
    col2.metric("Events / minute", f"{len(last_minute):,}")
    col3.metric("Unique editors", f"{df['user'].nunique():,}")
    col4.metric("Bot share", f"{df['bot'].mean():.0%}")
    col5.metric("New pages", f"{(df['type'] == 'new').sum():,}")
    col6.metric("Net bytes changed", f"{int(edits['byte_change'].sum()):+,}")

    # Activity over time, human vs bot
    activity = (
        df.set_index("received_at")
        .groupby("editor_type")
        .resample("10s")
        .size()
        .rename("events")
        .reset_index()
    )
    activity_chart = (
        alt.Chart(activity, title="Activity over time (events per 10 seconds)")
        .mark_line(strokeWidth=2)
        .encode(
            x=alt.X("received_at:T", title=None),
            y=alt.Y("events:Q", title="Events"),
            color=alt.Color(
                "editor_type:N",
                title=None,
                scale=alt.Scale(domain=["Human", "Bot"], range=[HUMAN_COLOR, BOT_COLOR]),
                legend=alt.Legend(orient="top"),
            ),
            tooltip=[
                alt.Tooltip("received_at:T", title="Time", format="%H:%M:%S"),
                alt.Tooltip("editor_type:N", title="Editor"),
                alt.Tooltip("events:Q", title="Events"),
            ],
        )
        .properties(height=260)
    )
    st.altair_chart(activity_chart, use_container_width=True)

    # Breakdowns
    left, middle, right = st.columns(3)
    left.altair_chart(bar_chart(df, "wiki", "Most active wikis"), use_container_width=True)
    middle.altair_chart(bar_chart(df, "type", "Event types"), use_container_width=True)
    right.altair_chart(bar_chart(df[~df["bot"]], "user", "Most active human editors"), use_container_width=True)

    # Trending pages and biggest changes
    left, right = st.columns(2)
    with left:
        st.subheader("Trending pages")
        trending = (
            df.groupby(["title", "wiki"])
            .agg(edits=("id", "size"), editors=("user", "nunique"), url=("url", "last"))
            .sort_values(["edits", "editors"], ascending=False)
            .head(10)
            .reset_index()
        )
        st.dataframe(
            trending,
            hide_index=True,
            use_container_width=True,
            column_config={"url": st.column_config.LinkColumn("Link", display_text="open")},
        )
    with right:
        st.subheader("Biggest changes")
        biggest = edits.dropna(subset=["byte_change"])
        biggest = biggest.reindex(biggest["byte_change"].abs().sort_values(ascending=False).index).head(10)
        st.dataframe(
            biggest[["title", "wiki", "user", "byte_change", "url"]],
            hide_index=True,
            use_container_width=True,
            column_config={
                "byte_change": st.column_config.NumberColumn("Bytes", format="%+d"),
                "url": st.column_config.LinkColumn("Link", display_text="open"),
            },
        )

    # Live feed
    st.subheader("Latest changes")
    latest = df.sort_values("received_at", ascending=False).head(50)
    st.dataframe(
        latest[["event_time", "type", "wiki", "title", "user", "bot", "minor", "byte_change", "comment", "url"]],
        hide_index=True,
        use_container_width=True,
        column_config={
            "event_time": st.column_config.DatetimeColumn("Time", format="HH:mm:ss"),
            "byte_change": st.column_config.NumberColumn("Bytes", format="%+d"),
            "url": st.column_config.LinkColumn("Link", display_text="open"),
        },
    )


render_dashboard()