# Product Requirements Document (PRD) for Summarization Scheduling System

## Table of Contents

1. [Introduction](#introduction)
2. [Overview](#overview)
3. [Database Schema](#database-schema)
   - [User Table](#user-table)
   - [Segment Table](#segment-table)
   - [Temp Segments Table](#temp-segments-table)
   - [Summaries Table](#summaries-table)
4. [Process Flow](#process-flow)
   - [Accumulating Segments](#accumulating-segments)
   - [Summarization Task](#summarization-task)
   - [Summarization Logic](#summarization-logic)
   - [Cleanup Locked Segments Task](#cleanup-locked-segments-task)
5. [Scheduler Configuration](#scheduler-configuration)
6. [Timestamps and Timezones](#timestamps-and-timezones)
7. [Error Handling and Retry Logic](#error-handling-and-retry-logic)
8. [Dependencies](#dependencies)
9. [Assumptions and Constraints](#assumptions-and-constraints)
10. [API Keys and Environment Variables](#api-keys-and-environment-variables)
11. [External Services Integration](#external-services-integration)

---

## Introduction

This document provides a comprehensive description of the summarization scheduling system, detailing how it interacts with the database, how tasks are scheduled, the structure of the database tables, and the precise flow of data through the system. It serves as a reference for developers to understand and recreate the summarization schedule and its associated components.

## Overview

The summarization system processes user-generated conversation segments to generate concise summaries using Large Language Models (LLMs). Segments are accumulated in real-time and stored temporarily. A scheduled task periodically processes these accumulated segments, generates summaries, and then stores them in the database. The system ensures efficient processing, handling of retries, and cleanup of stale data.

## Database Schema

The summarization system interacts with several database tables. Below are the details of each table and their relationships.

### User Table

Stores user information.

- **Table Name**: `user`
- **Columns**:
  - `id` (Integer, Primary Key)
  - `username` (String, Unique, Not Null)
  - `password` (String)
  - `uid` (String, Unique)
  - `email` (String, Unique)
  - `first_name` (String)
  - `last_name` (String)
  - `profile_picture` (String)
  - `timezone` (String)
  - `is_admin` (Boolean, Default `False`)

### Segment Table

Stores individual conversation segments associated with a user's session.

- **Table Name**: `segments`
- **Columns**:
  - `id` (Integer, Primary Key)
  - `main_id` (Integer, Foreign Key to `main.id`, Not Null)
  - `text` (Text, Not Null)
  - `speaker` (String, Not Null)
  - `speaker_id` (Integer)
  - `is_user` (Boolean, Not Null)
  - `start_time` (Float)
  - `end_time` (Float)
  - `timestamp` (DateTime with Timezone, Default `now()`)
  - `summary_id` (Integer, Foreign Key to `summaries.id`)
  - `processed` (Boolean, Default `False`)

### Temp Segments Table

Stores segments temporarily for summarization processing.

- **Table Name**: `temp_segments`
- **Columns**:
  - `id` (Integer, Primary Key)
  - `user_id` (Integer, Foreign Key to `user.id`, Not Null)
  - `segment_id` (Integer, Not Null)
  - `speaker` (String)
  - `text` (Text)
  - `timestamp` (DateTime with Timezone, Default `now()`)
  - `created_at` (DateTime with Timezone, Default `now()`)
  - `locked` (Boolean, Default `False`)
  - `lock_timestamp` (DateTime with Timezone)
  - `processed_at` (DateTime with Timezone)
  - `processing_attempts` (Integer, Default `0`)

- **Indexes**:
  - Index on `user_id` and `locked` for faster querying.

### Summaries Table

Stores generated summaries.

- **Table Name**: `summaries`
- **Columns**:
  - `id` (Integer, Primary Key)
  - `user_id` (Integer, Foreign Key to `user.id`, Not Null)
  - `headline` (Text, Not Null)
  - `bullet_points` (Array of Text, Not Null)
  - `tag` (String)
  - `fact_checker` (Array of Text)
  - `timestamp` (DateTime with Timezone, Default `now()`)
  - `created_at` (DateTime with Timezone, Default `now()`)

- **Relationships**:
  - One-to-many relationship with `segments` table via `summary_id`.

## Process Flow

### Accumulating Segments

- **Trigger**: When a conversation segment is received via the webhook.
- **Process**:
  1. The segment data is saved in the `segments` table.
  2. The segment is also stored in `temp_segments` for temporary storage, marked as unprocessed (`processed_at` is `NULL`).
  3. The `user_id` is associated with the segment based on the `uid` provided.

### Summarization Task

- **Trigger**: Scheduled to run every **5 minutes**.
- **Process**:
  1. **Selection of Users**: Fetch all users from the `user` table.
  2. **For Each User**:
     - Retrieve unprocessed segments from `temp_segments` where `processed_at` is `NULL` and `user_id` matches.
     - Order the segments by `timestamp` in ascending order.
     - **Processing Conditions**:
       - If there are at least **5 segments**, or
       - If the oldest unprocessed segment is at least **10 minutes** old.
     - If conditions are met, proceed to summarization.
  3. **Summarization**:
     - **Concatenate Text**: Combine the text of the selected segments into a single string.
     - **Minimum Length Check**: If the total text length is less than **50 characters**, increment `processing_attempts` and skip summarization.
     - **Generate Summary**: Use the concatenated text to generate a summary using LLMs.
     - **Post-Processing**:
       - If a summary is successfully generated:
         - Create a new record in the `summaries` table.
         - Update the corresponding segments in the `segments` table:
           - Set `processed` to `True`.
           - Link them via `summary_id`.
         - Delete the processed segments from `temp_segments`.
       - If summarization fails:
         - Increment `processing_attempts` for each segment.
         - Remove segments from `temp_segments` if `processing_attempts` exceed **3**.
  4. **Send to External Services**:
     - If a summary is generated, optionally send it to an external service (e.g., Reflect).
  5. **Logging**: Log successes, failures, and any errors encountered.

### Summarization Logic

- **Module**: `summarization.py`
- **Process**:
  - **Language Models Used**:
    - Supports both OpenAI's GPT-4 and Anthropic's Claude models.
    - Configured via `SUMMARY_MODEL` and `FACT_CHECK_MODEL` variables.
  - **Prompts**:
    - **Summary Prompt**: Custom prompt that guides the LLM to generate a concise headline and bullet points, including categories and context.
    - **Fact Check Prompt**: Prompts the LLM to identify any factual inaccuracies in the text.
  - **Functions**:
    - `generate_summary_part(text: str)`: Generates the summary (headline, bullet points, tag) using the summary prompt.
    - `generate_fact_check_part(text: str)`: Generates fact checks using the fact check prompt.
    - `combine_results(summary_part, fact_check_part)`: Combines the summary and fact check results into a single `Summary` object.
  - **Error Handling**:
    - If the LLM returns an "INSUFFICIENT_CONTEXT" response, the process returns `None` to indicate summarization should be skipped.
    - Exceptions during LLM calls are caught, logged, and cause the process to return `None`.
  - **Resetting Sequences**:
    - The `reset_sequence` function ensures that the auto-incrementing sequence for the `summaries` table starts from a specific value (`2000`) to prevent ID conflicts.

### Cleanup Locked Segments Task

- **Trigger**: Scheduled to run every **15 minutes**.
- **Process**:
  1. Identify segments in `temp_segments` where `locked` is `True` and `lock_timestamp` is older than **30 minutes**.
  2. Reset `locked` to `False` and `lock_timestamp` to `NULL` for these segments.
  3. Commit the changes to the database.
  4. **Logging**: Report the number of segments cleaned up or any errors.

## Scheduler Configuration

- **Scheduler**: Uses `APScheduler` with a background scheduler.
- **Jobs**:
  - **Summarization Task**:
    - Function: `summarization_task`
    - Trigger: Interval of **5 minutes**
    - Wrapped with `app.app_context()` to ensure proper Flask application context.
  - **Cleanup Locked Segments Task**:
    - Function: `cleanup_locked_segments`
    - Trigger: Interval of **15 minutes**
    - Wrapped with `app.app_context()`.

- **Initialization**:
  - Scheduler is initialized in `app.py` and starts immediately upon application startup.
  - Job functions are imported from `summarization_handler.py`.

## Timestamps and Timezones

- **Timestamps**:
  - All timestamp fields in the database are stored with timezone information (`timezone=True`).
  - `timestamp` fields generally use `func.now()` or `datetime.utcnow()` for consistency.
- **Timezones**:
  - Users can have a preferred timezone stored in the `timezone` field of the `user` table.
  - When displaying or processing times, the system converts UTC times to the user's local timezone as needed.
  - In the summarization and `send_to_reflect` functions, timestamps are converted to the user's timezone for accurate reporting.

## Error Handling and Retry Logic

- **Summarization Failures**:
  - If the summarization fails due to insufficient text length or other issues, the `processing_attempts` field in `temp_segments` is incremented.
  - Segments exceeding **3 processing attempts** are removed from `temp_segments` to prevent indefinite retries.
- **LLM Errors**:
  - Exceptions during calls to LLMs (e.g., API errors) are caught and logged.
  - The process handles failures gracefully to avoid crashing the scheduled task.
- **Database Transactions**:
  - Use of session transactions (`with session.begin()`) ensures atomicity.
  - Exceptions are caught and logged, with `session.rollback()` called to maintain database integrity.
- **Logging**:
  - The system logs important events, errors, and status messages to help with debugging and monitoring.

## Dependencies

- **Libraries and Frameworks**:
  - **Flask**: Web framework used for the application.
  - **SQLAlchemy**: ORM for database interactions.
  - **APScheduler**: For scheduling background tasks.
  - **Pytz**: For timezone conversions.
  - **Requests**: For making HTTP requests to external services.
  - **LangChain**: Used for chaining LLM prompts and parsing outputs.
  - **PyDantic**: For data validation and settings management.
  - **LLM SDKs**:
    - `langchain_openai`: For integrating with OpenAI's GPT models.
    - `langchain_anthropic`: For integrating with Anthropic's Claude models.

## Assumptions and Constraints

- **Assumptions**:
  - Users are properly registered and have valid `uid` and `user_id` associations.
  - Environment variables for external services (e.g., API keys for OpenAI, Anthropic, Reflect) are correctly set.
  - The LLMs used (OpenAI/Anthropic) are accessible and have sufficient quota.
- **Constraints**:
  - The database should support timezone-aware datetime fields.
  - The summarization models or services (`generate_summary` function) are operational and accessible.
  - The application is expected to run continuously to allow the scheduler to trigger tasks at the defined intervals.
  - The system relies on the stability and availability of external APIs (e.g., LLM providers).

## API Keys and Environment Variables

- **Required Environment Variables**:
  - `OPENAI_API_KEY`: API key for accessing OpenAI's GPT models.
  - `ANTHROPIC_API_KEY`: API key for accessing Anthropic's Claude models.
  - `REFLECT_GRAPH_ID`: Identifier for the Reflect graph (if integrating with Reflect).
  - `REFLECT_ACCESS_TOKEN`: Access token for authentication with Reflect.
- **Configuration**:
  - Environment variables should be securely stored and managed (e.g., using Replit Secrets).
  - The choice of LLM model can be configured via variables in `summarization.py`:
    - `SUMMARY_MODEL`: Set to `"openai"` or `"anthropic"`.
    - `FACT_CHECK_MODEL`: Set to `"openai"` or `"anthropic"`.

## External Services Integration

- **LLMs**:
  - The system uses LLMs to generate summaries and perform fact-checking.
  - **Prompt Engineering**:
    - Custom prompts are defined to guide the LLMs in generating the desired outputs.
    - Prompts include context, categories, and instructions for formatting the output in JSON.
  - **Output Parsing**:
    - The outputs from the LLMs are parsed and validated using PyDantic models to ensure they conform to the expected structure.

- **Reflect Integration**:
  - **Purpose**: Optionally send generated summaries to the Reflect app.
  - **Process**:
    - After successfully generating a summary, the system formats the summary according to Reflect's expected format.
    - An HTTP PUT request is made to Reflect's API endpoint with the formatted summary.
  - **Error Handling**:
    - Network or API errors during the Reflect integration are caught and logged.
    - The summarization process continues regardless of Reflect's response to avoid blocking.

---

**Note**: This document provides a detailed description of the summarization scheduling system, including database interactions, process flows, summarization logic, configurations, and dependencies. It should serve as a comprehensive guide for developers to understand and recreate the system as needed.