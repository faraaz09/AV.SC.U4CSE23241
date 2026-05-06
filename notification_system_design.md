# Notification System Design

---

## Stage 1

### Core Actions the Notification Platform Should Support

1. **Fetch all notifications** for a logged-in student (paginated)
2. **Fetch a single notification** by ID
3. **Mark one or all notifications as read**
4. **Delete a notification**
5. **Get unread count** (badge on UI)
6. **Create a notification** (admin / server-side only)
7. **Real-time delivery** of new notifications to connected students

---

### REST API Endpoints

All endpoints require an `Authorization: Bearer <token>` header.  
Base path: `/api/v1`

#### 1. Get notifications for a student

```
GET /api/v1/notifications
```

**Headers**
```
Authorization: Bearer <token>
Accept: application/json
```

**Query params**
| Param   | Type    | Description                             |
|---------|---------|-----------------------------------------|
| page    | integer | Page number (default: 1)                |
| limit   | integer | Items per page (default: 20, max: 100)  |
| type    | string  | Filter: `Placement`, `Result`, `Event`  |
| is_read | boolean | Filter by read status                   |

**Response 200**
```json
{
  "data": [
    {
      "id": "a3f1e2b0-...",
      "student_id": 1042,
      "type": "Placement",
      "message": "CSX Corporation hiring",
      "is_read": false,
      "created_at": "2026-04-22T17:51:18Z"
    }
  ],
  "meta": {
    "page": 1,
    "limit": 20,
    "total": 143,
    "unread_count": 7
  }
}
```

#### 2. Get a single notification

```
GET /api/v1/notifications/{id}
```

**Response 200**
```json
{
  "id": "a3f1e2b0-...",
  "student_id": 1042,
  "type": "Placement",
  "message": "CSX Corporation hiring",
  "is_read": false,
  "created_at": "2026-04-22T17:51:18Z"
}
```

**Response 404**
```json
{ "error": "notification_not_found" }
```

#### 3. Mark notification(s) as read

```
PATCH /api/v1/notifications/{id}/read
```

Mark all unread:
```
PATCH /api/v1/notifications/read-all
```

**Response 200**
```json
{ "updated": 1 }
```

#### 4. Delete a notification

```
DELETE /api/v1/notifications/{id}
```

**Response 204** — No content

#### 5. Get unread count

```
GET /api/v1/notifications/unread-count
```

**Response 200**
```json
{ "student_id": 1042, "unread_count": 7 }
```

#### 6. Create a notification (admin)

```
POST /api/v1/notifications
```

**Request body**
```json
{
  "student_id": 1042,
  "type": "Placement",
  "message": "Infosys hiring — apply by 2026-05-01"
}
```

**Response 201**
```json
{
  "id": "b7c2d3e4-...",
  "student_id": 1042,
  "type": "Placement",
  "message": "Infosys hiring — apply by 2026-05-01",
  "is_read": false,
  "created_at": "2026-04-22T18:00:00Z"
}
```

---

### Error Response Schema (all endpoints)

```json
{
  "error": "error_code",
  "message": "Human-readable description"
}
```

HTTP status codes used: `200`, `201`, `204`, `400`, `401`, `403`, `404`, `429`, `500`.

---

### Real-Time Notification Mechanism

**Approach: Server-Sent Events (SSE)**

SSE is chosen over WebSockets because notifications are **server-to-client only** (students never push data upstream). SSE uses plain HTTP, works through proxies and load balancers without special configuration, and auto-reconnects on disconnect.

```
GET /api/v1/notifications/stream
Authorization: Bearer <token>
Accept: text/event-stream
```

**Event format** (server pushes this when a new notification is created):
```
event: new_notification
data: {"id":"a3f...","type":"Placement","message":"AMD hiring","created_at":"2026-04-22T18:05:00Z"}

event: heartbeat
data: {}
```

**Flow**
```
Student opens app → connects to /stream → long-lived HTTP response
Admin creates notification → server publishes event to SSE channel → student receives push
```

For scale (50,000 concurrent students), the SSE channel is backed by a **Redis Pub/Sub** topic `notifications:{student_id}`. Each application server subscribes to the channels of its connected students and fans out events to SSE streams.

---

## Stage 2

### Recommended Database: PostgreSQL

**Rationale**:
- ACID guarantees — notification delivery status (is_read) must be consistent
- Rich indexing: composite indexes, partial indexes, index-only scans
- `ENUM` types for notification categories
- Mature JSON support for extensible payloads
- Read replicas for horizontal read scaling

---

### Database Schema

```sql
CREATE TYPE notification_type AS ENUM ('Event', 'Result', 'Placement');

CREATE TABLE students (
    id          BIGSERIAL       PRIMARY KEY,
    name        VARCHAR(255)    NOT NULL,
    email       VARCHAR(255)    UNIQUE NOT NULL,
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE TABLE notifications (
    id          UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id  BIGINT          NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    type        notification_type NOT NULL,
    message     TEXT            NOT NULL,
    is_read     BOOLEAN         NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
```

---

### SQL Queries Corresponding to Stage 1 APIs

**GET /api/v1/notifications** (paginated, unread only)
```sql
SELECT id, type, message, is_read, created_at
  FROM notifications
 WHERE student_id = $1
   AND is_read    = FALSE
 ORDER BY created_at DESC
 LIMIT $2 OFFSET $3;
```

**GET /api/v1/notifications/{id}**
```sql
SELECT id, student_id, type, message, is_read, created_at
  FROM notifications
 WHERE id = $1 AND student_id = $2;
```

**PATCH /api/v1/notifications/{id}/read**
```sql
UPDATE notifications
   SET is_read = TRUE
 WHERE id = $1 AND student_id = $2;
```

**PATCH /api/v1/notifications/read-all**
```sql
UPDATE notifications
   SET is_read = TRUE
 WHERE student_id = $1 AND is_read = FALSE;
```

**DELETE /api/v1/notifications/{id}**
```sql
DELETE FROM notifications
 WHERE id = $1 AND student_id = $2;
```

**GET /api/v1/notifications/unread-count**
```sql
SELECT COUNT(*) AS unread_count
  FROM notifications
 WHERE student_id = $1 AND is_read = FALSE;
```

**POST /api/v1/notifications** (create)
```sql
INSERT INTO notifications (student_id, type, message)
VALUES ($1, $2, $3)
RETURNING id, student_id, type, message, is_read, created_at;
```

---

### Problems as Data Volume Grows

| Problem | Cause | Solution |
|---|---|---|
| Slow reads | Full table scan on large `notifications` table | Composite indexes |
| Lock contention | Mass UPDATE (mark-all-read) locks many rows | Batch updates with `WHERE ctid IN (...)` |
| Storage bloat | 50k students × many notifications per student | Partition table by `student_id` range or time |
| Replication lag | All reads hit primary during high traffic | Read replicas for GET endpoints |

---

## Stage 3

### Query Analysis

```sql
SELECT * FROM notifications
 WHERE studentID = 1042 AND isRead = false
 ORDER BY createdAt DESC;
```

**Is the query accurate?**  
The logic is correct — it fetches all unread notifications for student 1042, newest first.

**Why is it slow?**

1. `SELECT *` — returns all columns (including potentially large `message` TEXT), increasing I/O.
2. **No index** on `(student_id, is_read)`. PostgreSQL must do a full sequential scan of 5,000,000 rows.
3. `ORDER BY created_at DESC` requires an additional **sort step** on the filtered result set.

**Estimated cost**: Full sequential scan of 5M rows → O(n). On a spinning disk this is several seconds; even on SSD it is hundreds of milliseconds.

**Fix — create a composite index**

```sql
-- Covers WHERE + ORDER BY in a single index scan (index-only scan possible)
CREATE INDEX idx_notif_student_unread_time
    ON notifications (student_id, is_read, created_at DESC)
    WHERE is_read = FALSE;   -- partial index: only unread rows indexed
```

The **partial index** (`WHERE is_read = FALSE`) is smaller, faster to build and maintain, and perfectly matches the most frequent query pattern.

**Improved query**

```sql
SELECT id, type, message, created_at        -- only needed columns
  FROM notifications
 WHERE student_id = 1042
   AND is_read    = FALSE
 ORDER BY created_at DESC
 LIMIT 50;                                  -- always paginate
```

---

### Should We Index Every Column?

**No.** This advice is not effective and is actively harmful:

- Each index consumes disk space and must be updated on every `INSERT` / `UPDATE` / `DELETE`.
- With 5M rows and bulk inserts (notify-all), write throughput degrades significantly.
- The query planner uses at most one or two indexes per query; unused indexes are pure overhead.
- **Rule**: index only columns used in `WHERE`, `ORDER BY`, `JOIN`, or `GROUP BY` of frequent queries.

---

### Query to Find Students Who Received a Placement Notification in the Last 7 Days

```sql
SELECT DISTINCT student_id
  FROM notifications
 WHERE type       = 'Placement'
   AND created_at >= NOW() - INTERVAL '7 days';
```

Supported by:
```sql
CREATE INDEX idx_notif_type_created
    ON notifications (type, created_at DESC);
```

---

## Stage 4

### Problem
Notifications are fetched on every page load for every student, overwhelming the DB with reads.

### Recommended Strategy: Redis Cache + Lazy Invalidation

**Architecture**

```
Client → App Server → Redis (cache) → PostgreSQL (miss only)
```

**Cache key**: `notifications:{student_id}:unread`  
**Value**: JSON array of latest 50 unread notifications  
**TTL**: 120 seconds

**Read path**
```
GET cache_key
  → HIT  : return cached data directly (sub-ms)
  → MISS  : query PostgreSQL → store result in Redis with TTL → return data
```

**Write path (new notification created)**
```
INSERT into PostgreSQL
→ DEL cache_key for that student (invalidate)
→ Publish SSE event
```

**Mark-as-read**
```
UPDATE notifications SET is_read=TRUE WHERE ...
→ DEL cache_key (invalidate so next read is fresh)
```

---

### Tradeoffs

| Strategy | Pros | Cons |
|---|---|---|
| **Redis cache** | 10–100× faster reads; DB offloaded | Stale window up to TTL; Redis memory cost; invalidation complexity |
| **Read replica** | No stale data; free reads from replica | Replica lag (ms–seconds); still DB-level latency |
| **Pagination** | Reduces row count per query | Doesn't help if every page load re-queries |
| **CDN (static)** | Global edge caching | Notifications are user-specific — CDN cache keys must include student token |

**Recommendation**: Redis cache (primary) + read replica (secondary) + server-side pagination. This combination reduces DB load by 90%+ in typical usage.

---

### Cache Stampede Prevention

When a hot student's cache expires simultaneously for many requests:

```python
# Use a probabilistic early expiry (XFetch algorithm)
# or a distributed lock (SET key ... NX EX 5) to let only one request
# rebuild the cache while others wait or return stale data.
```

---

## Stage 5

### Shortcomings of the Current Implementation

```
function notify_all(student_ids: array, message: string):
    for student_id in student_ids:
        send_email(...)    # synchronous HTTP call
        save_to_db(...)    # synchronous DB write
        push_to_app(...)   # synchronous push
```

1. **Sequential = slow**: 50,000 students × ~300ms per iteration ≈ **4+ hours** to complete.
2. **No retry**: If `send_email` fails for student #200, those 200 emails are lost permanently.
3. **No partial failure handling**: The loop halts on exceptions, leaving remaining students unnotified.
4. **Tight coupling**: Email API failure blocks DB save and push.
5. **No back-pressure**: All 50,000 HTTP calls fire simultaneously, DDOSing the email provider.

### What Happens When `send_email` Fails at Student #200?

In the current design: students #201–#50,000 receive no notification and no email. The system has no record of the failure. Recovery requires re-running the entire job or manually tracking which students were processed.

---

### Redesigned Implementation

**Key principles**:
- DB save is the **source of truth** and happens first (bulk insert, one transaction).
- Email and push are **asynchronous** tasks dispatched via a message queue.
- Each task is independently retryable.
- Email and DB save do **not** need to happen atomically — eventual consistency is acceptable (an email might arrive a few seconds after the DB record, which is fine).

```
function notify_all(student_ids: array, message: string):

    # Step 1 — Bulk insert all notifications in one transaction (fast, atomic)
    batch_insert_notifications(student_ids, message)
    # All students now have a DB record; this is the source of truth.

    # Step 2 — Enqueue async tasks (do NOT block here)
    for student_id in student_ids:
        enqueue_task(queue="email_queue",   payload={student_id, message})
        enqueue_task(queue="push_queue",    payload={student_id, message})
    # Returns immediately; workers process independently


# --- Email Worker (runs on N parallel worker processes) ---
function email_worker():
    loop:
        task = dequeue(queue="email_queue", visibility_timeout=30s)
        try:
            send_email(task.student_id, task.message)
            ack(task)                          # remove from queue on success
        except TransientError:
            nack(task)                         # return to queue → auto-retry
        except PermanentError:
            move_to_dead_letter_queue(task)    # alert on-call; do not retry
            ack(task)


# --- Push Worker (runs on M parallel worker processes) ---
function push_worker():
    loop:
        task = dequeue(queue="push_queue", visibility_timeout=10s)
        try:
            push_to_app(task.student_id, task.message)
            ack(task)
        except:
            nack(task)
```

**Why DB save and email sending should NOT be atomic**:
- Email delivery is inherently eventually consistent (SMTP does not provide transactional guarantees).
- Making them atomic via 2-phase commit would require distributed transactions — complex, slow, and fragile.
- Correct pattern: save to DB first (guaranteed), then send email (best-effort with retries). If the email never arrives, the student can still see the notification in the app.

**Queue technology**: AWS SQS, RabbitMQ, or Kafka. SQS provides at-least-once delivery with visibility timeout and dead-letter queues natively.

---

## Stage 6

### Priority Inbox — Design and Implementation

**Priority scoring rule**:
- **Type weight**: Placement = 3, Result = 2, Event = 1
- **Recency**: within the same type, newer timestamps rank higher
- Combined sort key: `(type_weight DESC, timestamp DESC)`

**Why this order?** A placement opportunity is time-critical and high-value regardless of age. A result notification is more actionable than a generic event. Within each category, newer information is more relevant.

**Implementation**: See `notification_app_be/app.py` — function `_top_n_inbox`

---

### Maintaining Top-N Efficiently as New Notifications Arrive

A **min-heap of size N** is the optimal data structure:

```
                 Min-Heap (size N)
              ┌─────────────────────┐
              │  Root = least       │
              │  important in top-N │
              │  (e.g. oldest Event)│
              └─────────────────────┘

New notification arrives:
  if heap.size < N          → push directly
  elif new > heap.root      → heapreplace(heap, new)   # O(log N)
  else                      → discard                  # O(1)
```

**Time complexity per new notification**: O(log N) — constant relative to total notification volume.  
**Space complexity**: O(N) — only top-N notifications stored in memory.

This is dramatically better than sorting the full list (O(total × log total)) on every update.

**Reading the top-N** (for display): sort the heap descending → O(N log N), but N is small (10–20).

---

### Sample Output (Mock Data, Top 10)

```
======================================================================
  PRIORITY INBOX — TOP 10 NOTIFICATIONS
  Scoring: Placement=3 > Result=2 > Event=1, then by recency
  Total fetched: 10
======================================================================
  # 1  [Placement]  weight=3  2026-04-22 17:51:18 UTC  CSX Corporation hiring
       ID: b283218f-ea5a-4b7c-93a9-1f2f240d64b0
  # 2  [Placement]  weight=3  2026-04-22 17:49:42 UTC  Advanced Micro Devices Inc. hiring
       ID: 8a7412bd-6065-4d09-8501-a37f11cc848b
  # 3  [Result   ]  weight=2  2026-04-22 17:51:30 UTC  mid-sem
       ID: d146095a-0d86-4a34-9e69-3900a14576bc
  # 4  [Result   ]  weight=2  2026-04-22 17:50:54 UTC  mid-sem
       ID: 0005513a-142b-4bbc-8678-eefec65e1ede
  # 5  [Result   ]  weight=2  2026-04-22 17:50:42 UTC  project-review
       ID: ea836726-c25e-4f21-a72f-544a6af8a37f
  # 6  [Result   ]  weight=2  2026-04-22 17:50:30 UTC  external
       ID: 003cb427-8fc6-47f7-bb00-be228f6b0d2c
  # 7  [Result   ]  weight=2  2026-04-22 17:50:18 UTC  project-review
       ID: e5c4ff20-31bf-4d40-8f02-72fda59e8918
  # 8  [Result   ]  weight=2  2026-04-22 17:49:54 UTC  project-review
       ID: cf2885a6-45ac-4ba0-b548-6e9e9d4c52c8
  # 9  [Event    ]  weight=1  2026-04-22 17:51:06 UTC  farewell
       ID: 81589ada-0ad3-4f77-9554-f52fb558e09d
  #10  [Event    ]  weight=1  2026-04-22 17:50:06 UTC  tech-fest
       ID: 1cfce5ee-ad37-4894-8946-d707627176a5
======================================================================
```
