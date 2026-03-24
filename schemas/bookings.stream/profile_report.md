# Stream Profile Report — bookings.stream

**Profiled:** 2026-03-24T13:30:16.734785+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 200  
**Parse success rate:** 100.0%  
**Discovery method:** event_type_field  
**Sub-schemas:** 4

---

## Sub-Schema Summary

| Cluster | Events | % Stream | Fields | Confidence | PII |
|---------|--------|----------|--------|------------|-----|
| `booking.cancelled` | 58 | 29% | 18 | 60% | `passengers[].first_name`, `passengers[].last_name`, `passengers[].date_of_birth` |
| `booking.created` | 53 | 26% | 18 | 60% | `passengers[].first_name`, `passengers[].last_name`, `passengers[].date_of_birth` |
| `booking.check_in` | 46 | 23% | 18 | 62% | `passengers[].first_name`, `passengers[].last_name`, `passengers[].date_of_birth` |
| `booking.amended` | 43 | 22% | 18 | 60% | `passengers[].first_name`, `passengers[].last_name`, `passengers[].date_of_birth` |

---

## `booking.cancelled`

- **Events:** 58 (29% of stream)
- **Top-level keys:** event_id, event_type, booking_reference, created_at, total_price, currency, cabin_class, contact_email, contact_phone, flights
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | uuid | ✓ | 99% | — |
| `event_type` | string | ✓ | 70% | — |
| `booking_reference` | string | ✓ | 70% | — |
| `created_at` | mixed | ✓ | 70% | — |
| `total_price` | mixed | ✓ | 70% | — |
| `currency` | string | ✓ | 70% | — |
| `cabin_class` | string | ✓ | 70% | — |
| `passengers` | array | ✓ | 69% | — |
| `passengers[].title` | string | ✓ | 69% | — |
| `passengers[].first_name` | string | ✓ | 69% | name |
| `passengers[].last_name` | string | ✓ | 69% | name |
| `passengers[].date_of_birth` | string | ✓ | 69% | date_of_birth, phone |
| `passengers[].passport_number` | string | ✓ | 69% | passport |
| `contact_email` | email | ✓ | 97% | email |
| `contact_phone` | string | ✓ | 70% | phone |
| `flights` | array | ✓ | 70% | — |
| `loyalty_number` | string | ✓ | 70% | loyalty_number, passport |
| `passenger_name` | string | ○ | 51% | name |

**PII in this cluster:** `passengers[].first_name` (name), `passengers[].last_name` (name), `passengers[].date_of_birth` (date_of_birth, phone), `passengers[].passport_number` (passport), `contact_email` (email), `contact_phone` (phone), `loyalty_number` (loyalty_number, passport), `passenger_name` (name)

---

## `booking.created`

- **Events:** 53 (26% of stream)
- **Top-level keys:** event_id, event_type, booking_reference, created_at, total_price, currency, cabin_class, contact_email, contact_phone, flights
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | uuid | ✓ | 99% | — |
| `event_type` | string | ✓ | 70% | — |
| `booking_reference` | string | ✓ | 70% | — |
| `created_at` | mixed | ✓ | 70% | — |
| `total_price` | float | ✓ | 70% | — |
| `currency` | string | ✓ | 70% | — |
| `cabin_class` | string | ✓ | 70% | — |
| `passengers` | array | ✓ | 69% | — |
| `passengers[].title` | string | ✓ | 69% | — |
| `passengers[].first_name` | string | ✓ | 69% | name |
| `passengers[].last_name` | string | ✓ | 69% | name |
| `passengers[].date_of_birth` | string | ✓ | 69% | date_of_birth, phone |
| `passengers[].passport_number` | string | ✓ | 69% | passport |
| `contact_email` | email | ✓ | 97% | email |
| `contact_phone` | string | ✓ | 70% | phone |
| `flights` | array | ✓ | 70% | — |
| `loyalty_number` | string | ✓ | 70% | loyalty_number, passport |
| `passenger_name` | string | ○ | 51% | name |

**PII in this cluster:** `passengers[].first_name` (name), `passengers[].last_name` (name), `passengers[].date_of_birth` (date_of_birth, phone), `passengers[].passport_number` (passport), `contact_email` (email), `contact_phone` (phone), `loyalty_number` (loyalty_number, passport), `passenger_name` (name)

---

## `booking.check_in`

- **Events:** 46 (23% of stream)
- **Top-level keys:** event_id, event_type, booking_reference, created_at, total_price, currency, cabin_class, contact_email, contact_phone, flights
- **Confidence:** 62%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | string | ✓ | 70% | — |
| `event_type` | string | ✓ | 70% | — |
| `booking_reference` | string | ✓ | 70% | — |
| `created_at` | mixed | ✓ | 70% | — |
| `total_price` | mixed | ✓ | 70% | — |
| `currency` | string | ✓ | 70% | — |
| `cabin_class` | string | ✓ | 70% | — |
| `passengers` | array | ✓ | 68% | — |
| `passengers[].title` | string | ✓ | 68% | — |
| `passengers[].first_name` | string | ✓ | 68% | name |
| `passengers[].last_name` | string | ✓ | 68% | name |
| `passengers[].date_of_birth` | string | ✓ | 68% | date_of_birth, phone |
| `passengers[].passport_number` | string | ✓ | 68% | passport |
| `contact_email` | string | ✓ | 70% | email |
| `contact_phone` | string | ✓ | 70% | phone |
| `flights` | array | ✓ | 70% | — |
| `loyalty_number` | string | ✓ | 70% | loyalty_number, passport |
| `passenger_name` | string | ○ | 52% | name |

**PII in this cluster:** `passengers[].first_name` (name), `passengers[].last_name` (name), `passengers[].date_of_birth` (date_of_birth, phone), `passengers[].passport_number` (passport), `contact_email` (email), `contact_phone` (phone), `loyalty_number` (loyalty_number, passport), `passenger_name` (name)

---

## `booking.amended`

- **Events:** 43 (22% of stream)
- **Top-level keys:** event_id, event_type, booking_reference, created_at, total_price, currency, cabin_class, contact_email, contact_phone, flights
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | string | ✓ | 70% | — |
| `event_type` | string | ✓ | 70% | — |
| `booking_reference` | string | ✓ | 70% | — |
| `created_at` | mixed | ✓ | 70% | — |
| `total_price` | mixed | ✓ | 70% | — |
| `currency` | string | ✓ | 70% | — |
| `cabin_class` | string | ✓ | 70% | — |
| `passengers` | array | ✓ | 69% | — |
| `passengers[].title` | string | ✓ | 69% | — |
| `passengers[].first_name` | string | ✓ | 69% | name |
| `passengers[].last_name` | string | ✓ | 69% | name |
| `passengers[].date_of_birth` | string | ✓ | 69% | date_of_birth, phone |
| `passengers[].passport_number` | string | ✓ | 69% | passport |
| `contact_email` | string | ✓ | 70% | email |
| `contact_phone` | string | ✓ | 70% | phone |
| `flights` | array | ✓ | 70% | — |
| `loyalty_number` | string | ✓ | 70% | loyalty_number, passport |
| `passenger_name` | string | ○ | 51% | name |

**PII in this cluster:** `passengers[].first_name` (name), `passengers[].last_name` (name), `passengers[].date_of_birth` (date_of_birth, phone), `passengers[].passport_number` (passport), `contact_email` (email), `contact_phone` (phone), `loyalty_number` (loyalty_number, passport), `passenger_name` (name)
