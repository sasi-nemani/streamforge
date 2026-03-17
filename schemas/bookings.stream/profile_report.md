# Stream Profile Report — bookings.stream

**Profiled:** 2026-03-14T11:18:37.520943+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 250  
**Parse success rate:** 100.0%  
**Discovery method:** event_type_field  
**Sub-schemas:** 4

---

## Sub-Schema Summary

| Cluster | Events | % Stream | Fields | Confidence | PII |
|---------|--------|----------|--------|------------|-----|
| `booking.cancelled` | 69 | 28% | 18 | 85% | `contact_email`, `contact_phone`, `loyalty_number` |
| `booking.created` | 65 | 26% | 20 | 92% | `contact_email`, `contact_phone`, `loyalty_number` |
| `booking.amended` | 60 | 24% | 17 | 90% | `contact_email`, `contact_phone`, `passengers[].first_name` |
| `booking.check_in` | 56 | 22% | 18 | 60% | `passengers[].first_name`, `passengers[].last_name`, `passengers[].date_of_birth` |

---

## `booking.cancelled`

- **Events:** 69 (28% of stream)
- **Top-level keys:** event_id, event_type, booking_reference, created_at, total_price, currency, cabin_class, contact_email, contact_phone, flights
- **Confidence:** 85%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | uuid | ✓ | 90% | — |
| `event_type` | string | ✓ | 90% | — |
| `booking_reference` | string | ✓ | 90% | — |
| `created_at` | mixed | ✓ | 80% | — |
| `total_price` | float | ✓ | 90% | — |
| `currency` | string | ✓ | 90% | — |
| `cabin_class` | string | ✓ | 90% | — |
| `contact_email` | email | ✓ | 90% | email |
| `contact_phone` | phone | ✓ | 90% | phone |
| `flights` | array | ✓ | 90% | — |
| `flights[]` | string | ✓ | 90% | — |
| `loyalty_number` | string | ○ | 80% | passport, loyalty_number |
| `passengers` | array | ○ | 80% | — |
| `passengers[].title` | string | ○ | 80% | — |
| `passengers[].first_name` | string | ○ | 80% | name |
| `passengers[].last_name` | string | ○ | 80% | name |
| `passengers[].date_of_birth` | string | ○ | 80% | date_of_birth, phone |
| `passengers[].passport_number` | string | ○ | 80% | passport |

**PII in this cluster:** `contact_email` (email), `contact_phone` (phone), `loyalty_number` (passport, loyalty_number), `passengers[].first_name` (name), `passengers[].last_name` (name), `passengers[].date_of_birth` (date_of_birth, phone), `passengers[].passport_number` (passport)

---

## `booking.created`

- **Events:** 65 (26% of stream)
- **Top-level keys:** event_id, event_type, booking_reference, created_at, total_price, currency, cabin_class, contact_email, contact_phone, flights
- **Confidence:** 92%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | uuid | ✓ | 95% | — |
| `event_type` | string | ✓ | 95% | — |
| `booking_reference` | string | ✓ | 95% | — |
| `created_at` | mixed | ✓ | 90% | — |
| `total_price` | float | ✓ | 95% | — |
| `currency` | string | ✓ | 95% | — |
| `cabin_class` | string | ✓ | 95% | — |
| `contact_email` | email | ✓ | 95% | email |
| `contact_phone` | string | ✓ | 95% | phone |
| `flights` | array | ✓ | 95% | — |
| `flights[]` | string | ✓ | 95% | — |
| `loyalty_number` | string | ○ | 80% | passport, loyalty_number |
| `passengers` | array | ✓ | 95% | — |
| `passengers[]` | object | ✓ | 95% | — |
| `passengers[].title` | string | ✓ | 95% | — |
| `passengers[].first_name` | string | ✓ | 95% | name |
| `passengers[].last_name` | string | ✓ | 95% | name |
| `passengers[].date_of_birth` | string | ✓ | 95% | date_of_birth, phone |
| `passengers[].passport_number` | string | ○ | 80% | passport |
| `passenger_name` | string | ○ | 50% | name |

**PII in this cluster:** `contact_email` (email), `contact_phone` (phone), `loyalty_number` (passport, loyalty_number), `passengers[].first_name` (name), `passengers[].last_name` (name), `passengers[].date_of_birth` (date_of_birth, phone), `passengers[].passport_number` (passport), `passenger_name` (name)

---

## `booking.amended`

- **Events:** 60 (24% of stream)
- **Top-level keys:** event_id, event_type, booking_reference, created_at, total_price, currency, cabin_class, contact_email, contact_phone, flights
- **Confidence:** 90%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | uuid | ✓ | 95% | — |
| `event_type` | string | ✓ | 95% | — |
| `booking_reference` | string | ✓ | 95% | — |
| `created_at` | mixed | ✓ | 80% | — |
| `total_price` | float | ✓ | 95% | — |
| `currency` | string | ✓ | 95% | — |
| `cabin_class` | string | ✓ | 95% | — |
| `contact_email` | email | ✓ | 95% | email |
| `contact_phone` | phone | ✓ | 95% | phone |
| `flights` | array | ✓ | 95% | — |
| `passengers` | array | ○ | 80% | — |
| `passengers[].title` | string | ○ | 80% | — |
| `passengers[].first_name` | string | ○ | 80% | name |
| `passengers[].last_name` | string | ○ | 80% | name |
| `passengers[].date_of_birth` | string | ○ | 80% | date_of_birth, phone |
| `passengers[].passport_number` | string | ○ | 80% | passport |
| `loyalty_number` | string | ○ | 80% | passport, loyalty_number |

**PII in this cluster:** `contact_email` (email), `contact_phone` (phone), `passengers[].first_name` (name), `passengers[].last_name` (name), `passengers[].date_of_birth` (date_of_birth, phone), `passengers[].passport_number` (passport), `loyalty_number` (passport, loyalty_number)

---

## `booking.check_in`

- **Events:** 56 (22% of stream)
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
| `loyalty_number` | string | ✓ | 70% | passport, loyalty_number |
| `passenger_name` | string | ○ | 51% | name |

**PII in this cluster:** `passengers[].first_name` (name), `passengers[].last_name` (name), `passengers[].date_of_birth` (date_of_birth, phone), `passengers[].passport_number` (passport), `contact_email` (email), `contact_phone` (phone), `loyalty_number` (passport, loyalty_number), `passenger_name` (name)
