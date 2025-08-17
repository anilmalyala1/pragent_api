from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from langchain_core.output_parsers import JsonOutputParser
from langchain.output_parsers import OutputFixingParser

from dotenv import load_dotenv,find_dotenv



load_dotenv(find_dotenv(),override=True)

class Patch(BaseModel):
    before: str = Field(..., description="Exact code snippet before the change")
    after: str = Field(..., description="Exact code snippet after the change")

class ToolIssue(BaseModel):
    severity: Literal["critical", "major", "minor"] = Field(..., description="Severity level of the issue")
    category: Literal["security", "quality", "performance", "best_practice"] = Field(..., description="Type of issue")
    title: str = Field(..., description="Short descriptive title")
    description: str = Field(..., description="1-2 line explanation of the issue")
    line: Optional[int] = Field(None, description="Line number where the issue occurs")
    patch: Optional[Patch] = Field(None, description="Optional fix with before/after code")

class EmitIssuesArgs(BaseModel):
    issues: List[ToolIssue] = Field(..., description="List of issues found in the changed lines")

parser = JsonOutputParser(pydantic_object=EmitIssuesArgs)

from langchain.prompts import ChatPromptTemplate, PromptTemplate

prompt = PromptTemplate(
    template="""
You are an experienced senior code reviewer specializing in security, performance, and best practices.

Your task:
1. Focus only on the CHANGED_LINES provided. Do not review unchanged code unless necessary for context.
2. Return your review findings strictly in JSON format matching the provided schema.

Guidelines for "line" numbers:
- Match the exact line numbers as shown in the snippet.
- If the snippet starts at line 1, first line = 1.
- If the snippet starts at line 50, first line = 50.

{format_instructions}

CHANGED_LINES:
{diff}
""",
    input_variables=["diff"],
    partial_variables={"format_instructions": parser.get_format_instructions()},
)

chat_prompt = ChatPromptTemplate.from_messages([
    ("system", "You are an experienced senior code reviewer specializing in security, performance, and best practices. Respond ONLY with valid JSON matching the schema."),
    ("system", "{format_instructions}"),
    ("user", "Review ONLY the CHANGED_LINES. Use exact line numbers.\n\nCHANGED_LINES:\n{diff}")
]).partial(format_instructions=parser.get_format_instructions())

from langchain_openai.chat_models import ChatOpenAI

model = ChatOpenAI(model="gpt-4o-mini", temperature=0)

fixing_output_parser=OutputFixingParser.from_llm(parser=parser,llm=model)

#chain = prompt | model | fixing_output_parser

chain = chat_prompt | model | fixing_output_parser

diff_text = """
50: password = request.form['password']
51: authenticate_user(username, password)
"""

result = chain.invoke({"diff": diff_text})

print(result)

