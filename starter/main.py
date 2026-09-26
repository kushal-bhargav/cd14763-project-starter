"""
Customer Support AI Agent — Starter Code
==========================================
Your task is to complete this file by implementing all sections marked
with # TODO comments.

Reference the step-by-step solution files and INSTRUCTIONS.md for guidance.
Do NOT copy the solution directly — work through each section yourself.

Run locally (after filling in config values):
  uv run main.py '{"prompt": "Hello", "customer_id": "CUST-123", "session_id": "s1"}'

Deploy to AgentCore:
  agentcore deploy

Invoke deployed agent:
  agentcore invoke '{"prompt": "Hello", "customer_id": "CUST-123", "session_id": "s1"}'
"""

# ── Imports ───────────────────────────────────────────────────────────────────
# These imports are provided. Do not remove them.
from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.memory import MemoryClient
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient
from mcp.client.streamable_http import streamable_http_client
import argparse, json
import os, asyncio, boto3
from strands.hooks import (
    HookProvider, AfterInvocationEvent, HookRegistry, MessageAddedEvent,
)
import logging
import uuid
from typing import Dict
from bedrock_agentcore.tools.code_interpreter_client import code_session
from strands_tools.browser import AgentCoreBrowser


logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("CSAI_Agent")

# ── TODO 1 — App Initialisation ───────────────────────────────────────────────
# Create a BedrockAgentCoreApp instance.
# This registers the ASGI server for AgentCore deployment.
# There must be exactly one instance per deployment.
#
# Hint: app = BedrockAgentCoreApp()

# TODO: Create the BedrockAgentCoreApp instance
app = BedrockAgentCoreApp()
print("Stage: App initialized")


# Suppress interactive tool-consent prompts (required in headless deployments).
os.environ["BYPASS_TOOL_CONSENT"] = "true"


# ── TODO 2 — Configuration ────────────────────────────────────────────────────
# Replace the placeholder strings with your actual AWS resource values.
# You collected these in Part 1 of the INSTRUCTIONS.
#
# GATEWAY_URL format: https://<alias>.gateway.bedrock-agentcore.<region>.amazonaws.com/mcp
# KB_ID       format: 10-character alphanumeric string from the KB console
# REGION:     your AWS region, e.g. "us-east-1"
# MEMORY_ID   format: shown in the AgentCore Memory console

GATEWAY_URL = "https://customersupportgateway-8lyuhwkb1s.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
KB_ID       = "JRLH9THITV"
REGION      = "us-east-1"
MEMORY_ID   = "CustomerSupportMemory-oOFd3NBjtp"


# ── TODO 3 — Model and Clients ────────────────────────────────────────────────
# Create:
#   1. A BedrockModel using model_id "global.amazon.nova-2-lite-v1:0"
#   2. A MemoryClient with region_name=REGION
#   3. A boto3 client for the "bedrock-agent-runtime" service in REGION
#
# Hint: model = BedrockModel(model_id=model_id)

model_id = "global.amazon.nova-2-lite-v1:0"

# TODO: Create the BedrockModel instance
model = BedrockModel(model_id=model_id)

# TODO: Create the MemoryClient instance
memory_client = MemoryClient(region_name=REGION)

# TODO: Create the boto3 bedrock-agent-runtime client
_bedrock_runtime = boto3.client("bedrock-agent-runtime", region_name=REGION)
print("Stage: Model and clients initialized")


# ── TODO 4 — Namespace Helper ─────────────────────────────────────────────────
# Implement get_namespaces() to return a dict mapping strategy type to
# namespace template string.
#
# Steps:
#   1. Call mem_client.get_memory_strategies(memory_id) to get strategy list
#   2. Return a dict: { strategy["type"]: strategy["namespaces"][0] for each strategy }
#
# Example output:
#   { "SEMANTIC": "cs_agent/{actorId}/facts",
#     "USER_PREFERENCE": "cs_agent/{actorId}/preferences" }

def get_namespaces(mem_client: MemoryClient, memory_id: str) -> Dict:
    """Return a dict mapping strategy type → namespace template string."""
    print("Stage: Loading memory namespaces")
    response = mem_client.get_memory_strategies(memory_id)

    if isinstance(response, dict):
        strategies = (
            response.get("strategies")
            or response.get("memoryStrategies")
            or response.get("strategyList")
            or []
        )
    else:
        strategies = response or []

    namespaces = {}

    for strategy in strategies:
        if not isinstance(strategy, dict):
            continue

        strategy_type = strategy.get("type") or strategy.get("strategyType")
        namespace_values = (
            strategy.get("namespaces")
            or strategy.get("namespaceTemplates")
            or []
        )

        if isinstance(namespace_values, dict):
            namespace_values = list(namespace_values.values())

        if strategy_type and namespace_values:
            namespaces[strategy_type] = namespace_values[0]

    return namespaces


# ── TODO 5 — Memory Hook ──────────────────────────────────────────────────────
# Implement MemoryHook, a HookProvider subclass that adds long-term memory.
#
# The class needs:
#   __init__(self, actor_id, session_id, memory_client, memory_id)
#     — store all four as instance attributes
#     — call get_namespaces() and store the result as self.namespaces
#
#   retrieve_customer_context(self, event: MessageAddedEvent)
#     — only runs for plain-text user messages (not tool results)
#     — for each strategy namespace, call memory_client.retrieve_memories(
#          memory_id, namespace (formatted with actorId), query, top_k=5)
#     — collect non-empty memory texts tagged with their strategy type
#     — if any memories found, prepend them to the user message as:
#          "Customer Context:\n<memories>\n\n<original_message>"
#
#   save_support_interaction(self, event: AfterInvocationEvent)
#     — walk the message list backwards to find the last plain-text user
#       query and the last assistant response
#     — call memory_client.create_event(memory_id, actor_id, session_id,
#          messages=[(customer_query, "USER"), (agent_response, "ASSISTANT")])
#
#   register_hooks(self, registry: HookRegistry)
#     — register retrieve_customer_context on MessageAddedEvent
#     — register save_support_interaction on AfterInvocationEvent

class MemoryHook(HookProvider):
    """Long-term memory hook for the customer support agent."""

    def __init__(
        self,
        actor_id: str,
        session_id: str,
        memory_client: MemoryClient,
        memory_id: str,
    ):
        self.actor_id = actor_id
        self.session_id = session_id
        self.memory_client = memory_client
        self.memory_id = memory_id
        self.namespaces = get_namespaces(memory_client, memory_id)
        self.last_user_query = None

    def retrieve_customer_context(self, event: MessageAddedEvent):
        """Retrieve relevant memories and prepend them to the user message."""
        message = getattr(event, "message", None)

        if message is None:
            agent = getattr(event, "agent", None)
            messages = getattr(agent, "messages", []) if agent is not None else []
            message = messages[-1] if messages else None

        if not isinstance(message, dict):
            return

        if message.get("role") != "user":
            return

        content = message.get("content")
        if not isinstance(content, list):
            return

        text_blocks = [
            block.get("text", "").strip()
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        ]

        if len(text_blocks) != 1 or not text_blocks[0]:
            return

        user_query = text_blocks[0]
        self.last_user_query = user_query
        collected_memories = []

        for strategy_type, namespace_template in self.namespaces.items():
            try:
                namespace = namespace_template.format(
                    actorId=self.actor_id,
                    sessionId=self.session_id,
                )
                memories = self.memory_client.retrieve_memories(
                    memory_id=self.memory_id,
                    namespace=namespace,
                    query=user_query,
                    top_k=5,
                )

                for memory in memories or []:
                    if not isinstance(memory, dict):
                        continue

                    memory_content = memory.get("content", {})
                    memory_text = (
                        memory_content.get("text", "").strip()
                        if isinstance(memory_content, dict)
                        else ""
                    )

                    if memory_text:
                        collected_memories.append(
                            f"[{strategy_type.upper()}] {memory_text}"
                        )
            except Exception as exc:
                logger.warning(
                    "Memory retrieval failed for strategy %s: %s",
                    strategy_type,
                    exc,
                )

        if collected_memories:
            context_text = "\n".join(collected_memories)
            message["content"] = [
                {
                    "text": (
                        f"Customer Context:\n{context_text}\n\n{user_query}"
                    )
                }
            ]

    def save_support_interaction(self, event: AfterInvocationEvent):
        """Save the completed turn to memory after the agent responds."""
        customer_query = self.last_user_query
        agent_response = None

        agent = getattr(event, "agent", None)
        messages = getattr(agent, "messages", []) if agent is not None else []

        if customer_query is None and isinstance(messages, list):
            for message in reversed(messages):
                if not isinstance(message, dict) or message.get("role") != "user":
                    continue

                content = message.get("content")
                if not isinstance(content, list):
                    continue

                text_blocks = [
                    block.get("text", "").strip()
                    for block in content
                    if isinstance(block, dict) and isinstance(block.get("text"), str)
                ]

                if len(text_blocks) == 1 and text_blocks[0]:
                    customer_query = text_blocks[0]
                    break

        result = getattr(event, "result", None)
        result_message = getattr(result, "message", None) if result is not None else None

        if isinstance(result_message, dict):
            result_content = result_message.get("content", [])
            if isinstance(result_content, list):
                result_text = [
                    block.get("text", "").strip()
                    for block in result_content
                    if isinstance(block, dict) and isinstance(block.get("text"), str)
                ]
                if result_text:
                    agent_response = "\n".join(t for t in result_text if t)

        if agent_response is None and isinstance(messages, list):
            for message in reversed(messages):
                if not isinstance(message, dict) or message.get("role") != "assistant":
                    continue

                content = message.get("content")
                if not isinstance(content, list):
                    continue

                text_blocks = [
                    block.get("text", "").strip()
                    for block in content
                    if isinstance(block, dict) and isinstance(block.get("text"), str)
                ]

                if text_blocks:
                    agent_response = "\n".join(t for t in text_blocks if t)
                    break

        if customer_query and agent_response:
            try:
                self.memory_client.create_event(
                    self.memory_id,
                    self.actor_id,
                    self.session_id,
                    messages=[
                        (customer_query, "USER"),
                        (agent_response, "ASSISTANT"),
                    ],
                )
            except Exception as exc:
                logger.warning("Memory save failed: %s", exc)

    def register_hooks(self, registry: HookRegistry) -> None:  # type: ignore
        """Register both memory callbacks."""
        registry.add_callback(
            MessageAddedEvent,
            self.retrieve_customer_context,
        )
        registry.add_callback(
            AfterInvocationEvent,
            self.save_support_interaction,
        )


# ── TODO 6 — Knowledge Base Tool ─────────────────────────────────────────────
# Implement search_knowledge_base(query) using the @tool decorator.
#
# Steps:
#   1. Guard: if KB_ID is empty return "Knowledge base not configured."
#   2. Call _bedrock_runtime.retrieve(
#          knowledgeBaseId=KB_ID,
#          retrievalQuery={"text": query}
#      )
#   3. Extract resp["retrievalResults"]; return a message if empty
#   4. Join the text chunks with "\n---\n" and return the result
#
# The docstring is the tool description — the model uses it to decide when
# to call this tool, so keep it clear and accurate.

@tool
def search_knowledge_base(query: str) -> str:
    """
    Search the Amazon product catalog and support knowledge base.
    Use this for product specifications, return policies, warranty
    information, loyalty program details, and order status definitions.

    Args:
        query: The question or topic to search for

    Returns:
        Relevant information retrieved from the knowledge base
    """
    print("Stage: Knowledge base search started")
    if not KB_ID or not KB_ID.strip() or KB_ID.startswith("<"):
        return "Knowledge base not configured."

    try:
        response = _bedrock_runtime.retrieve(
            knowledgeBaseId=KB_ID,
            retrievalQuery={"text": query},
        )
        results = response.get("retrievalResults", [])

        if not results:
            return "No relevant information was found in the knowledge base."

        chunks = []
        for result in results:
            if not isinstance(result, dict):
                continue

            content = result.get("content", {})
            text = (
                content.get("text", "").strip()
                if isinstance(content, dict)
                else ""
            )

            if text:
                chunks.append(text)

        if not chunks:
            return "No relevant information was found in the knowledge base."

        return "\n---\n".join(chunks)

    except Exception as e:
        logger.warning("Knowledge Base retrieval failed: %s", e)
        return f"Knowledge base search failed: {e}"


# ── TODO 7 — Loyalty Discount Tool (Code Interpreter) ────────────────────────
# Implement calculate_loyalty_discount() using the @tool decorator.
#
# The tool must:
#   1. Build a self-contained Python code string that:
#        • Defines earn_rates: {"standard": 1, "device": 2, "fresh": 5}
#        • Defines tier_rates: {"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}
#        • Calculates points_redeemed (floor to nearest 500, cap at 50% of order)
#        • Calculates tier_discount (applied to subtotal after points)
#        • Calculates final_total, total_savings, points_earned, remaining_points
#        • Prints a JSON result dict
#   2. Execute the code with code_session(REGION).invoke("executeCode", {...})
#      using language="python" and clearContext=True
#   3. Return the first result event as a JSON string
#   4. Include a fallback that computes only the tier discount if the
#      Code Interpreter is unavailable

@tool
def calculate_loyalty_discount(
    loyalty_points: int,
    tier: str,
    order_total: float,
    product_category: str = "standard",
) -> str:
    """
    Calculate the loyalty discount for a customer order using the
    AgentCore Code Interpreter. Runs exact arithmetic in a secure sandbox.

    Args:
        loyalty_points:   Customer's current points balance
        tier:             Customer tier — Silver, Gold, or Platinum
        order_total:      Order total in USD
        product_category: standard, device, or fresh

    Returns:
        Full discount breakdown and final price
    """
    print("Stage: Loyalty discount calculation started")
    safe_tier = str(tier).strip().title()
    safe_category = str(product_category).strip().lower()
    safe_points = max(0, int(loyalty_points))
    safe_order_total = max(0.0, float(order_total))

    code = f"""
import json
import math

earn_rates = {{"standard": 1, "device": 2, "fresh": 5}}
tier_rates = {{"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}}

loyalty_points = {safe_points}
tier = {json.dumps(safe_tier)}
order_total = {safe_order_total}
product_category = {json.dumps(safe_category)}

points_value_usd = 0.01
tier_discount_pct = tier_rates.get(tier, 0.00)

maximum_points_by_order = math.floor(
    (order_total * 0.50) / points_value_usd / 500
) * 500

points_redeemed = min(
    math.floor(loyalty_points / 500) * 500,
    maximum_points_by_order,
)

points_discount = points_redeemed * points_value_usd
subtotal_after_points = max(0.0, order_total - points_discount)
tier_discount = subtotal_after_points * tier_discount_pct
final_total = max(0.0, subtotal_after_points - tier_discount)
total_savings = order_total - final_total

points_earned = math.floor(
    final_total * earn_rates.get(product_category, 1)
)
remaining_points = loyalty_points - points_redeemed

result = {{
    "points_redeemed": int(points_redeemed),
    "tier_discount_pct": tier_discount_pct * 100,
    "tier_discount": round(tier_discount, 2),
    "points_discount": round(points_discount, 2),
    "final_total": round(final_total, 2),
    "total_savings": round(total_savings, 2),
    "points_earned": int(points_earned),
    "remaining_points": int(remaining_points),
}}

print(json.dumps(result))
"""

    try:
        with code_session(REGION) as code_client:
            response = code_client.invoke(
                "executeCode",
                {
                    "code": code,
                    "language": "python",
                    "clearContext": True,
                },
            )

        for event in response.get("stream", []):
            if not isinstance(event, dict):
                continue

            result = event.get("result")
            if result is not None:
                if isinstance(result, str):
                    return result
                return json.dumps(result)

        raise RuntimeError("Code Interpreter returned no result event.")

    except Exception as e:
        tier_discount_pct = {
            "Silver": 0.00,
            "Gold": 0.10,
            "Platinum": 0.15,
        }.get(safe_tier, 0.00)

        final_total = max(
            0.0,
            safe_order_total * (1.0 - tier_discount_pct),
        )

        fallback_result = {
            "points_redeemed": 0,
            "tier_discount_pct": tier_discount_pct * 100,
            "tier_discount": round(
                safe_order_total * tier_discount_pct, 2
            ),
            "points_discount": 0.0,
            "final_total": round(final_total, 2),
            "total_savings": round(
                safe_order_total - final_total, 2
            ),
            "points_earned": 0,
            "remaining_points": safe_points,
            "calculation_mode": "tier_only_fallback",
            "warning": f"Code Interpreter unavailable: {e}",
        }
        return json.dumps(fallback_result)


# ── TODO 8 — Agent Entrypoint ─────────────────────────────────────────────────
# Implement the invoke() function decorated with @app.entrypoint.
#
# Steps:
#   1. Extract user_input, actor_id, and session_id from the payload
#      (generate a UUID if session_id is missing)
#   2. Instantiate MemoryHook for this actor/session
#   3. Instantiate AgentCoreBrowser(region=REGION)
#   4. Build the tools list: [search_knowledge_base, calculate_loyalty_discount,
#                              agent_core_browser.browser]
#   5. Connect to the Gateway via MCPClient, load gateway_tools, extend tools list
#   6. Create and invoke the Agent with all tools, hooks, and system_prompt
#   7. Return the text from the first content block of the response
#   8. Handle exceptions gracefully

@app.entrypoint
async def invoke(payload, context=None):
    """
    Main handler called by AgentCore for every incoming request.

    Expected payload keys:
      prompt      (str, required) — the customer's message
      customer_id (str, optional) — unique customer identifier
      session_id  (str, optional) — session identifier; generated if absent
    """
    try:
        print("Stage: Agent invocation started")
        if not isinstance(payload, dict):
            raise ValueError("Payload must be a JSON object.")

        user_input = payload.get("prompt")
        if not isinstance(user_input, str) or not user_input.strip():
            raise ValueError("Missing required payload field: prompt")

        actor_id = str(payload.get("customer_id") or "anonymous")
        session_id = str(payload.get("session_id") or uuid.uuid4())

        memory_hook = MemoryHook(
            actor_id=actor_id,
            session_id=session_id,
            memory_client=memory_client,
            memory_id=MEMORY_ID,
        )

        agent_core_browser = AgentCoreBrowser(region=REGION)

        tools = [
            search_knowledge_base,
            calculate_loyalty_discount,
            agent_core_browser.browser,
        ]

        mcp_client = MCPClient(
            lambda: streamable_http_client(GATEWAY_URL)
        )

        system_prompt = """
You are a customer support AI agent for an Amazon-style retail business.

Use the available tools deliberately:
- Use the Knowledge Base tool for product specifications, return policies,
  warranties, loyalty program details, and other catalog/support information.
- Use the Gateway order tools for order and customer information.
- Use the Gateway refund tools for refund and return-label operations.
- Use the loyalty discount tool for loyalty calculations.
- Use the Browser tool when the user explicitly asks you to visit or inspect
  a live web page.

Ground factual answers in tool results when a relevant tool is available.
For calculations, use the loyalty discount tool rather than estimating.
Do not invent order, refund, customer, policy, or product details.
Be concise unless the customer asks for more detail.
"""

        with mcp_client:
            print("Stage: Loading gateway tools")
            gateway_tools = mcp_client.list_tools_sync()
            tools.extend(gateway_tools)

            print("Stage: Creating agent")
            agent = Agent(
                model=model,
                tools=tools,
                hooks=[memory_hook],
                system_prompt=system_prompt,
                callback_handler=None,
            )

            print("Stage: Invoking agent")
            response = agent(user_input)

        print("Stage: Agent response received")
        message = getattr(response, "message", None)
        content = message.get("content", []) if isinstance(message, dict) else []

        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    return text

        return str(response)

    except Exception as e:
        print("Stage: Agent invocation failed")
        logger.exception("Agent invocation failed")
        return f"Agent invocation failed: {e}"


# ── CLI entry point (do not modify) ──────────────────────────────────────────
def main():
    """Run one invocation from the command line for local testing."""
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", type=str)
    args = parser.parse_args()
    response = asyncio.run(invoke(json.loads(args.payload)))
    print(response)


if __name__ == "__main__":
    app.run()
    # Uncomment the line below and comment app.run() for local CLI testing:
    # main()