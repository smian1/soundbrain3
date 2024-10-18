from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain.chat_models.base import BaseChatModel
from langchain.prompts import ChatPromptTemplate
from langchain.output_parsers import PydanticOutputParser
from langchain_core.runnables import RunnablePassthrough
from config import Config
from pydantic import BaseModel, Field
from typing import List, Optional
import logging
import os
from datetime import datetime, timezone
import pytz
from sqlalchemy import text
from models import summaries as SummaryModel
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

CATEGORIES = [
    'personal', 'education', 'health', 'finance', 'legal', 'philosophy',
    'spiritual', 'science', 'entrepreneurship', 'parenting', 'romantic',
    'travel', 'inspiration', 'technology', 'business', 'social', 'work',
    'sports', 'other'
]

FORMATTED_CATEGORIES = "\n".join(f"- {category}" for category in CATEGORIES)

SUMMARY_PROMPT = """
Current date and time: {current_datetime}

Context (use only if relevant to the conversation):
<context>
The user is Salman, a 45-year-old VP of Solution Engineering pre-sales living in Hillsboro,OR. He is married to Farah, and they have one child name Armaan. Armaan is 5 years old born on 10/24/2019. Salman works at Salesforce, where his direct emmloyees include Anthony, Trace, Tarcy, Rob, Sandeep, Brent. Salman hobbies include tinkering, latest gadgets, and reading latest AI news.  He is forward thinking and loves to learn new things. He works remotely and travels sometimes. Farah is stay at home mom. Armaan just started pre-school. Have a dog name Gizmo. Gizmo is a Lhasa Apso. Gizmo is 14 yeras old. Gizmo has a brother name Shaggy who is 6 months younger than Gizmo and live in Seattle . Shaggy's pet mom is Farah's Aliyah. Who  lives in Settle and is a CIO at United Health Group Optoum. 
</context>

Analyze the provided conversation fragments and create a concise summary. Focus on the main topic, participants, and key points. Use the context above only if it's directly relevant to the conversation; do not force its inclusion if it doesn't naturally fit.

Categories for classification:
<categories>
{categories}
</categories>

Conversation fragments:
<conversation_fragments>
{text}
</conversation_fragments>

Analyze the provided fragments carefully. Try to identify the main topic, participants, and key points of the conversation. Keep in mind that these could be parts of discussions between family members, personal monologues, or work-related conversations.

Create your summary in the following format:

1. Choose an appropriate emoji that represents the overall theme or tone of the conversation.
2. Write a brief, catchy headline (5-10 words) that encapsulates the main topic as discussed in the conversation. Use headline capitalization (capitalize the first letter of each major word).
3. Identify key points from the conversation, using bullet points for each. Include as many bullet points as necessary to capture the full context and essence of the conversation.
4. Important: Report the information exactly as it appears in the conversation, even if it seems incorrect or implausible. Do not analyze or correct the information in the headline or bullet points.
5. Highlight important details such as names of people or places, book titles, or any specific claims made in the conversation.
6. Ensure that the summary captures the essence of the conversation in a comprehensive manner, reflecting what was actually said or discussed.
7. Always include any facts, assumptions, or information that is provided in the conversation fragments, reporting them as they appear without judgment.
8. Always include KPIs and metrics if provided in the conversation fragments, exactly as they are stated.
9. Classify the content into one of the categories provided earlier. Choose the category that best fits the overall theme or main topic of the conversation.
10. Ignore any information that doesn't add value to the summary. This could be random out-of-context comments, like turning on lights or telling a dog to go potty. Only include significant points of discussion; otherwise, ignore them.
11. If there's insufficient context, respond with: "INSUFFICIENT_CONTEXT". This should happen very rarely. 
12. you will do your best to summarize the conversation and provide a meaningful summary. 

Provide your summary in the following JSON format:

```json
{{
    "headline": "[Emoji] [Your headline here]",
    "bullet_points": [
        "[Key point 1]",
        "[Key point 2]",
        "[Key point 3]"
    ],
    "tag": "[category]"
}}
```

If there's insufficient context, respond with:
```json
{{
    "headline": "INSUFFICIENT_CONTEXT",
    "bullet_points": [],
    "tag": null
}}
```
"""

FACT_CHECK_PROMPT = """
Current date and time: {current_datetime}

Review the conversation fragments and identify any clear, unambiguous factual errors. Focus only on statements that can be definitively proven false.

Conversation fragments:
<conversation_fragments>
{text}
</conversation_fragments>

For each factual error:
1. State the incorrect claim briefly.
2. Provide a short, direct correction.
3. Format as: "Incorrect: [brief incorrect claim]. Fact: [concise correction]."

Provide your fact-check results in this JSON format:
```json
{{
    "fact_checks": [
        "Incorrect: [brief incorrect claim]. Fact: [concise correction]"
    ]
}}
```

If no factual errors are found, return:
```json
{{
    "fact_checks": []
}}
```
"""

class PartialSummary(BaseModel):
    headline: str = Field(..., description="The headline of the summary")
    bullet_points: List[str] = Field(..., description="List of key points in the summary")
    tag: Optional[str] = Field(None, description="One-word tag for the summary")

class FactCheck(BaseModel):
    fact_checks: List[str] = Field(default_factory=list, description="List of incorrect or fake facts found in the conversation")

class Summary(BaseModel):
    headline: str = Field(..., description="The headline of the summary")
    bullet_points: List[str] = Field(..., description="List of key points in the summary")
    tag: Optional[str] = Field(None, description="One-word tag for the summary")
    fact_checker: Optional[List[str]] = Field(None, description="List of incorrect or fake facts found in the conversation")

def get_llm(model_name: str) -> BaseChatModel:
    if model_name == "anthropic":
        return ChatAnthropic(
            model="claude-3-5-sonnet-20240620",
            anthropic_api_key=os.environ['ANTHROPIC_API_KEY'],
            max_tokens=3000,
            temperature=0.5
        )
    elif model_name == "openai":
        return ChatOpenAI(
            model="gpt-4o",
            #model="gpt-4o-mini",
            openai_api_key=os.environ['OPENAI_API_KEY'],
            max_tokens=2000,
            temperature=0.5
        )
    else:
        raise ValueError(f"Unsupported model: {model_name}")

# Update these variables to easily switch models
SUMMARY_MODEL = "openai"
FACT_CHECK_MODEL = "openai"

def generate_summary_part(text: str) -> PartialSummary:
    llm = get_llm(SUMMARY_MODEL)
    summary_prompt = ChatPromptTemplate.from_messages([("human", SUMMARY_PROMPT)])
    summary_chain = summary_prompt | llm | PydanticOutputParser(pydantic_object=PartialSummary)
    pacific_tz = pytz.timezone('US/Pacific')
    current_datetime = datetime.now(pacific_tz).strftime("%Y-%m-%d %H:%M:%S %Z")
    return summary_chain.invoke({"categories": FORMATTED_CATEGORIES, "text": text, "current_datetime": current_datetime})

def generate_fact_check_part(text: str) -> FactCheck:
    llm = get_llm(FACT_CHECK_MODEL)
    fact_check_prompt = ChatPromptTemplate.from_messages([("human", FACT_CHECK_PROMPT)])
    fact_check_chain = fact_check_prompt | llm | PydanticOutputParser(pydantic_object=FactCheck)
    pacific_tz = pytz.timezone('US/Pacific')
    current_datetime = datetime.now(pacific_tz).strftime("%Y-%m-%d %H:%M:%S %Z")
    return fact_check_chain.invoke({"text": text, "current_datetime": current_datetime})

def combine_results(summary_part: PartialSummary, fact_check_part: FactCheck) -> Summary:
    return Summary(
        headline=summary_part.headline,
        bullet_points=summary_part.bullet_points,
        tag=summary_part.tag,
        fact_checker=fact_check_part.fact_checks
    )

def generate_summary(text: str, session, user_id: int, first_segment_timestamp: datetime) -> Optional[Summary]:
    logger.debug(f"Starting generate_summary for text of length: {len(text)}")
    try:
        logger.debug("Generating summary part")
        summary_part = generate_summary_part(text)
        
        if summary_part.headline == "INSUFFICIENT_CONTEXT":
            logger.debug("Insufficient context detected, returning None")
            return None
        
        logger.debug(f"Generated summary part: {summary_part}")
        
        logger.debug("Generating fact check part")
        fact_check_part = generate_fact_check_part(text)
        logger.debug(f"Generated fact check part: {fact_check_part}")
        
        result = combine_results(summary_part, fact_check_part)
        logger.debug(f"Combined result: {result}")
        
        # Remove or comment out the reset_sequence call
        # reset_sequence(session, 'summaries', start_from=2000)
        
        # Create a new SummaryModel instance
        new_summary = SummaryModel(
            user_id=user_id,
            headline=result.headline,
            bullet_points=result.bullet_points,
            tag=result.tag,
            fact_checker=result.fact_checker,
            timestamp=first_segment_timestamp  # Use the timestamp of the first segment
        )
        
        session.add(new_summary)
        session.flush()
        # No need to commit here, as it's handled in the calling function
        
        return result
    except Exception as e:
        logger.error(f"Unexpected error in generate_summary: {str(e)}", exc_info=True)
        return None

def reset_sequence(session, table_name, id_column='id', start_from=2000):
    """Reset the auto-incrementing sequence for a given table."""
    conn = session.connection()
    try:
        # Get the maximum id value
        max_id = conn.execute(text(f"SELECT MAX({id_column}) FROM {table_name}")).scalar()
        
        # Use the larger of max_id + 1, start_from, or the current sequence value
        current_value = conn.execute(text(f"SELECT last_value FROM {table_name}_{id_column}_seq")).scalar()
        next_id = max((max_id + 1) if max_id else start_from, start_from, (current_value + 1) if current_value else start_from)
        
        # Set the sequence to start from the next available id
        conn.execute(text(f"ALTER SEQUENCE {table_name}_{id_column}_seq RESTART WITH {next_id}"))
        
        # Do not commit here; let the session handle it
        # Remove: conn.execute(text("COMMIT"))

        logger.info(f"Reset sequence for {table_name} to start from {next_id}")
    except Exception as e:
        logger.error(f"Error resetting sequence for {table_name}: {str(e)}")
        raise  # Re-raise the exception to be handled by the calling function