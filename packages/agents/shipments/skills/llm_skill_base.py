"""
LLM Skill Base Class - Reusable LLM execution pattern for shipment skills.

Provides common functionality for converting deterministic skills to LLM-powered skills:
- Record trimming to reduce prompt size
- OpenAI client management
- Structured JSON output parsing
- Error handling with deterministic fallback
- Token tracking and logging
"""

import json
import os
from typing import Any, Callable, Dict, List, Optional
from datetime import datetime

from openai import OpenAI
from openai.types.responses import Response

from packages.shared.logging import get_logger
from packages.agents.shipments.skills.record_trimmer import trim_records
from packages.agents.shipments.skills.loader import load_skill_instructions

logger = get_logger(__name__)


class LLMSkillExecutor:
    """
    Base class for LLM-powered skill execution.
    
    Encapsulates the common pattern:
    1. Trim records to relevant fields (274 -> 26 fields)
    2. Build context with baseline metrics
    3. Call OpenAI with system prompt from SKILL.md
    4. Parse structured JSON output
    5. Validate and return results
    
    Usage:
        executor = LLMSkillExecutor("shipment_health_check")
        result = executor.execute_with_llm(
            records=shipment_records,
            baseline=baseline_metrics,
            context={"customer_id": "123", "zip_benchmark": {...}}
        )
    """
    
    def __init__(
        self,
        skill_name: str,
        model: Optional[str] = None,
        timeout: float = 600.0,
        reasoning_effort: str = "medium"
    ):
        """
        Initialize LLM skill executor.
        
        Args:
            skill_name: Name of the skill (must match folder name)
            model: OpenAI model to use (defaults to OPENAI_MODEL env var)
            timeout: API call timeout in seconds
            reasoning_effort: Reasoning effort level (low, medium, high)
        """
        self.skill_name = skill_name
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-5-nano-2025-08-07")
        self.timeout = timeout
        self.reasoning_effort = reasoning_effort
        self.logger = get_logger(f"skills.{skill_name}")
        
        # Lazy-init OpenAI client
        self._client: Optional[OpenAI] = None
    
    @property
    def client(self) -> OpenAI:
        """Lazy-initialize OpenAI client."""
        if self._client is None:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY environment variable not set")
            self._client = OpenAI(api_key=api_key, timeout=self.timeout)
        return self._client
    
    def execute_with_llm(
        self,
        records: List[Dict[str, Any]],
        baseline: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        deterministic_fallback: Optional[Callable] = None,
        max_records: int = 50
    ) -> Dict[str, Any]:
        """
        Execute LLM analysis on shipment records.
        
        Args:
            records: List of shipment records (will be trimmed)
            baseline: Baseline metrics (avg_ctd, threshold, etc.)
            context: Additional context (customer_id, benchmarks, etc.)
            deterministic_fallback: Function to call if LLM fails
            max_records: Maximum records to send to LLM (for cost control)
        
        Returns:
            Skill result dict with grounded_metrics, qualitative_observations, etc.
        """
        start_time = datetime.utcnow()
        context = context or {}
        
        try:
            # Step 1: Trim records to relevant fields (274 -> 26)
            trimmed_records = trim_records(records[:max_records])
            
            self.logger.info(
                f"Executing {self.skill_name} with LLM",
                record_count=len(trimmed_records),
                model=self.model
            )
            
            # Step 2: Load system prompt from SKILL.md
            skill_instructions = load_skill_instructions(self.skill_name)
            system_prompt = self._extract_system_prompt(skill_instructions)
            
            # Step 3: Build user prompt with data
            user_prompt = self._build_user_prompt(trimmed_records, baseline, context)
            
            # Step 4: Call OpenAI API
            response = self._call_openai(system_prompt, user_prompt)
            
            # Step 5: Parse and validate response
            result = self._parse_response(response, context)
            
            # Add execution metadata
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            result["execution_time_seconds"] = execution_time
            result["llm_used"] = True
            result["skill"] = self.skill_name
            
            self.logger.info(
                f"{self.skill_name} completed successfully",
                execution_time=execution_time,
                llm_model=self.model
            )
            
            return result
            
        except Exception as e:
            self.logger.error(
                f"LLM execution failed for {self.skill_name}: {str(e)}"
            )
            
            # Fall back to deterministic if provided
            if deterministic_fallback:
                self.logger.warning(f"Falling back to deterministic calculation")
                try:
                    fallback_result = deterministic_fallback(records, baseline, context)
                    fallback_result["llm_used"] = False
                    fallback_result["llm_fallback"] = True
                    fallback_result["llm_error"] = str(e)
                    return fallback_result
                except Exception as fallback_error:
                    self.logger.error(f"Deterministic fallback also failed: {fallback_error}")
            
            # Return error result if no fallback or fallback failed
            return {
                "skill": self.skill_name,
                "error": f"LLM execution failed: {str(e)}",
                "llm_used": False,
                "grounded_metrics": {
                    "total_shipments": len(records),
                    "status": "ERROR"
                },
                "qualitative_observations": [
                    f"Analysis failed: {str(e)}",
                    "Unable to complete skill execution"
                ]
            }
    
    def _extract_system_prompt(self, skill_instructions: str) -> str:
        """
        Extract system prompt from SKILL.md content.
        
        For LLM-powered skills, the entire SKILL.md after frontmatter becomes the system prompt.
        Strips YAML frontmatter if present.
        
        Args:
            skill_instructions: Full SKILL.md content
        
        Returns:
            System prompt string
        """
        # Remove YAML frontmatter if present
        if skill_instructions.startswith("---"):
            parts = skill_instructions.split("---", 2)
            if len(parts) >= 3:
                return parts[2].strip()
        
        return skill_instructions.strip()
    
    def _build_user_prompt(
        self,
        records: List[Dict[str, Any]],
        baseline: Dict[str, Any],
        context: Dict[str, Any]
    ) -> str:
        """
        Build user prompt with data for LLM analysis.
        
        Args:
            records: Trimmed shipment records
            baseline: Baseline metrics
            context: Additional context
        
        Returns:
            JSON-formatted prompt string
        """
        prompt_data = {
            "customer_id": context.get("customer_id", "unknown"),
            "shipment_records": records,
            "baseline_metrics": baseline,
            "analysis_context": {
                "total_records": len(records),
                "record_fields": list(records[0].keys()) if records else [],
            }
        }
        
        # Add any additional context
        for key, value in context.items():
            if key not in prompt_data and key != "customer_id":
                prompt_data[key] = value
        
        return json.dumps(prompt_data, indent=2, default=str)
    
    def _call_openai(self, system_prompt: str, user_prompt: str) -> Response:
        """
        Call OpenAI API with system and user prompts.
        
        Args:
            system_prompt: System instructions from SKILL.md
            user_prompt: User data prompt (JSON)
        
        Returns:
            OpenAI response object
        """
        response = self.client.responses.create(
            model=self.model,
            reasoning={"effort": self.reasoning_effort},
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            text={"format": {"type": "json_object"}},
        )
        
        return response
    
    def _parse_response(
        self,
        response: Response,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Parse and validate LLM response.
        
        Args:
            response: OpenAI response object
            context: Request context for validation
        
        Returns:
            Parsed result dictionary
        
        Raises:
            json.JSONDecodeError: If response is not valid JSON
            ValueError: If response is missing required fields
        """
        content = response.output_text.strip()
        
        # Strip markdown code blocks if present
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()
        
        # Parse JSON
        result = json.loads(content)
        
        # Validate required fields
        if "grounded_metrics" not in result:
            self.logger.warning(
                f"LLM response missing 'grounded_metrics', adding empty dict"
            )
            result["grounded_metrics"] = {}
        
        return result
    
    def execute_with_preprocessing(
        self,
        records: List[Dict[str, Any]],
        preprocess_fn: Callable[[List[Dict]], Dict[str, Any]],
        deterministic_fallback: Optional[Callable] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute with custom preprocessing function.
        
        Useful when skill needs to compute baseline metrics in Python before LLM call.
        
        Args:
            records: Raw shipment records
            preprocess_fn: Function that takes records and returns baseline dict
            deterministic_fallback: Fallback function if LLM fails
            context: Additional context
        
        Returns:
            Skill result dictionary
        """
        # Run preprocessing to compute baseline metrics
        baseline = preprocess_fn(records)
        
        # Execute with LLM
        return self.execute_with_llm(
            records=records,
            baseline=baseline,
            context=context,
            deterministic_fallback=deterministic_fallback
        )


def create_deterministic_fallback(
    skill_name: str,
    basic_metrics_fn: Callable[[List[Dict], Dict], Dict[str, Any]]
) -> Callable:
    """
    Helper to create a standard deterministic fallback function.
    
    Args:
        skill_name: Name of the skill
        basic_metrics_fn: Function that computes basic metrics from records
    
    Returns:
        Fallback function that can be passed to execute_with_llm
    """
    def fallback(records: List[Dict], baseline: Dict, context: Dict) -> Dict[str, Any]:
        """Deterministic fallback calculation."""
        metrics = basic_metrics_fn(records, baseline)
        
        return {
            "skill": skill_name,
            "grounded_metrics": metrics,
            "qualitative_observations": [
                "LLM analysis unavailable",
                "Showing basic deterministic metrics only"
            ],
            "llm_fallback": True
        }
    
    return fallback
