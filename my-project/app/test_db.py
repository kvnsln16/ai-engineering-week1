from db import (
    get_or_create_source,
    insert_raw_signal
)

source_id = get_or_create_source(
    name="reddit",
    source_type="api",
    base_url="https://reddit.com"
)

insert_raw_signal(
    source_id=source_id,
    external_id="abc123",
    title="Test Post",
    content="This is a test signal",
    payload={
        "test": True
    }
)

print("Inserted successfully!")