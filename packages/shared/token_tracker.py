"""
Token consumption tracking for LLM usage across all shipments agents and skills.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class TokenTracker:
    """Token consumption tracking for LLM usage across all shipments agents."""

    def __init__(self, customer_id: Optional[str] = None, agent_name: str = "unknown"):
        self.customer_id = customer_id
        self.agent_name = agent_name
        self.session_start = datetime.now()
        self.session_tokens = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "api_calls": 0,
            "total_cost": 0.0,
        }
        self.call_history: List[Dict[str, Any]] = []

        # Create tracking directory
        self.tracking_dir = Path("output/token_tracking")
        self.tracking_dir.mkdir(parents=True, exist_ok=True)

        # Initialize session tracking file
        self.session_file = self.tracking_dir / f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    def track_api_call(self, response: Any, model: str = "gpt-5-nano-2025-08-07", custom_cost: Optional[float] = None):
        """Track a single API call's token consumption."""
        try:
            if hasattr(response, "usage"):
                usage = response.usage
                if hasattr(usage, "prompt_tokens"):
                    prompt_tokens = usage.prompt_tokens
                    completion_tokens = usage.completion_tokens
                    total_tokens = usage.total_tokens
                elif hasattr(usage, "input_tokens"):
                    prompt_tokens = usage.input_tokens
                    completion_tokens = usage.output_tokens
                    total_tokens = (
                        usage.total_tokens if hasattr(usage, "total_tokens") else (prompt_tokens + completion_tokens)
                    )
                else:
                    prompt_tokens = getattr(usage, "input_tokens", 0) or getattr(usage, "prompt_tokens", 0)
                    completion_tokens = getattr(usage, "output_tokens", 0) or getattr(usage, "completion_tokens", 0)
                    total_tokens = prompt_tokens + completion_tokens
            else:
                prompt_tokens = 0
                completion_tokens = 0
                total_tokens = 0

            cost = self._calculate_cost(prompt_tokens, completion_tokens, model, custom_cost)

            self.session_tokens["prompt_tokens"] += prompt_tokens
            self.session_tokens["completion_tokens"] += completion_tokens
            self.session_tokens["total_tokens"] += total_tokens
            self.session_tokens["api_calls"] += 1
            self.session_tokens["total_cost"] += cost

            call_record = {
                "timestamp": datetime.now().isoformat(),
                "agent": self.agent_name,
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "cost": cost,
                "customer_id": self.customer_id,
            }
            self.call_history.append(call_record)

            return call_record

        except Exception:
            return None

    def _calculate_cost(
        self, prompt_tokens: int, completion_tokens: int, model: str, custom_cost: Optional[float] = None
    ) -> float:
        """Calculate API cost based on token usage and model pricing."""
        if custom_cost is not None:
            return custom_cost

        pricing = {
            "gpt-4": {"prompt": 0.03, "completion": 0.06},
            "gpt-4-turbo": {"prompt": 0.01, "completion": 0.03},
            "gpt-4.1-2025-04-14": {"prompt": 0.03, "completion": 0.06},
            "gpt-4o": {"prompt": 0.005, "completion": 0.015},
            "gpt-5-nano-2025-08-07": {"prompt": 0.002, "completion": 0.008},
            "o3-2025-04-16": {"prompt": 0.10, "completion": 0.30},
            "gpt-3.5-turbo": {"prompt": 0.001, "completion": 0.002},
        }

        model_pricing = pricing.get(model, pricing.get("gpt-5-nano-2025-08-07", {"prompt": 0.002, "completion": 0.008}))

        prompt_cost = (prompt_tokens / 1000) * model_pricing["prompt"]
        completion_cost = (completion_tokens / 1000) * model_pricing["completion"]

        return prompt_cost + completion_cost

    def print_session_summary(self):
        """Print a summary of the entire session's token usage."""
        duration = (datetime.now() - self.session_start).total_seconds()

        print(f"\nSESSION SUMMARY [{self.agent_name}]")
        print("=" * 50)
        print(f"Customer ID: {self.customer_id}")
        print(f"Duration: {duration:.1f} seconds")
        print(f"API Calls: {self.session_tokens['api_calls']}")
        print(f"Total Tokens: {self.session_tokens['total_tokens']:,}")
        print(f"  Prompt: {self.session_tokens['prompt_tokens']:,}")
        print(f"  Completion: {self.session_tokens['completion_tokens']:,}")
        print(f"Total Cost: ${self.session_tokens['total_cost']:.4f}")

    def save_session_data(self):
        """Save session data to JSON file."""
        session_data = {
            "session_info": {
                "customer_id": self.customer_id,
                "agent_name": self.agent_name,
                "start_time": self.session_start.isoformat(),
                "end_time": datetime.now().isoformat(),
                "duration_seconds": (datetime.now() - self.session_start).total_seconds(),
            },
            "totals": self.session_tokens,
            "call_history": self.call_history,
        }

        try:
            with open(self.session_file, "w") as f:
                json.dump(session_data, f, indent=2)
        except Exception:
            pass

    def get_daily_summary(self, date: Optional[str] = None) -> Dict[str, Any]:
        """Get token usage summary for a specific date."""
        if date is None:
            date = datetime.now().strftime("%Y%m%d")

        daily_files = list(self.tracking_dir.glob(f"session_{date}_*.json"))

        daily_totals: Dict[str, Any] = {
            "total_tokens": 0,
            "total_cost": 0.0,
            "api_calls": 0,
            "agents_used": set(),
            "customers_analyzed": set(),
        }

        for file_path in daily_files:
            try:
                with open(file_path, "r") as f:
                    data = json.load(f)

                daily_totals["total_tokens"] += data["totals"]["total_tokens"]
                daily_totals["total_cost"] += data["totals"]["total_cost"]
                daily_totals["api_calls"] += data["totals"]["api_calls"]
                daily_totals["agents_used"].add(data["session_info"]["agent_name"])
                if data["session_info"]["customer_id"]:
                    daily_totals["customers_analyzed"].add(data["session_info"]["customer_id"])

            except Exception:
                pass

        daily_totals["agents_used"] = list(daily_totals["agents_used"])
        daily_totals["customers_analyzed"] = list(daily_totals["customers_analyzed"])

        return daily_totals


def create_tracker(customer_id: Optional[str] = None, agent_name: str = "unknown") -> TokenTracker:
    """Create a new token tracker instance."""
    return TokenTracker(customer_id, agent_name)
