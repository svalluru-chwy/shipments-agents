"""
Test LLM-powered skills vs deterministic baseline.

Runs converted skills with LLM and compares output to deterministic fallback.
Measures execution time, cost, and output quality differences.

Usage:
    python test_llm_vs_deterministic.py --customer-id 6180005 --skill shipment_health_check
    python test_llm_vs_deterministic.py --customer-id 6180005 --all-skills
"""

import argparse
import json
import os
import time
from datetime import datetime
from typing import Dict, Any, List
from pathlib import Path

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from packages.shared.s3 import S3Client
from packages.shared.config import get_settings
from packages.shared.logging import get_logger
from packages.agents.shipments.skills.runner import run_skill

logger = get_logger(__name__)


def load_customer_data(customer_id: str, s3_client: S3Client) -> Dict[str, Any]:
    """
    Load customer shipment data from S3.
    
    Args:
        customer_id: Customer ID
        s3_client: S3 client instance
    
    Returns:
        Dict with shipment data and metadata
    """
    logger.info(f"Loading data for customer {customer_id} from S3")
    
    settings = get_settings()
    base_path = settings.s3.base_path
    
    # Find and load main shipment data (JSON format)
    main_shipment_key = s3_client.find_latest_customer_file(
        customer_id, "data/main_shipment_query", base_path, suffix=".json"
    )
    if not main_shipment_key:
        raise FileNotFoundError(f"No main shipment data found for customer {customer_id}")
    
    main_shipment = s3_client.download_json(main_shipment_key)
    
    # Load benchmarks (optional)
    customer_zip_key = s3_client.find_latest_customer_file(
        customer_id, "data/customer_zip_performance", base_path, suffix=".json"
    )
    benchmark_zip_key = s3_client.find_latest_customer_file(
        customer_id, "data/benchmark_zip_performance", base_path, suffix=".json"
    )
    
    customer_zip = s3_client.download_json(customer_zip_key) if customer_zip_key else {}
    benchmark_zip = s3_client.download_json(benchmark_zip_key) if benchmark_zip_key else {}
    
    # Extract records from S3 JSON structure
    records = main_shipment.get("data", []) if isinstance(main_shipment, dict) else main_shipment
    if isinstance(records, dict) and "records" in records:
        records = records["records"]
    
    # Build state dict
    state = {
        "customer_id": customer_id,
        "shipment_data": {
            "records": records,
            "customer_zip_performance": customer_zip,
            "benchmark_zip_performance": benchmark_zip
        }
    }
    
    logger.info(f"Loaded {len(state['shipment_data']['records'])} records for customer {customer_id}")
    
    return state


def run_skill_test(
    skill_name: str,
    state: Dict[str, Any],
    test_llm: bool = True,
    test_fallback: bool = True
) -> Dict[str, Any]:
    """
    Run skill test comparing LLM vs deterministic.
    
    Args:
        skill_name: Name of skill to test
        state: State dict with customer data
        test_llm: Whether to test LLM version
        test_fallback: Whether to test deterministic fallback
    
    Returns:
        Test results dict
    """
    results = {
        "skill_name": skill_name,
        "customer_id": state.get("customer_id"),
        "timestamp": datetime.utcnow().isoformat(),
        "llm_result": None,
        "fallback_result": None,
        "comparison": {}
    }
    
    # Test LLM version
    if test_llm:
        logger.info(f"Testing LLM version of {skill_name}")
        start_time = time.time()
        
        try:
            llm_result = run_skill(skill_name, state)
            execution_time = time.time() - start_time
            
            results["llm_result"] = {
                "output": llm_result,
                "execution_time_seconds": execution_time,
                "llm_used": llm_result.get("llm_used", False),
                "error": llm_result.get("error"),
                "success": "error" not in llm_result
            }
            
            logger.info(f"LLM version completed in {execution_time:.2f}s")
            
        except Exception as e:
            logger.error(f"LLM version failed: {e}")
            results["llm_result"] = {
                "output": None,
                "execution_time_seconds": time.time() - start_time,
                "error": str(e),
                "success": False
            }
    
    # Test deterministic fallback (simulate LLM failure)
    if test_fallback:
        logger.info(f"Testing deterministic fallback for {skill_name}")
        start_time = time.time()
        
        try:
            # Temporarily disable OpenAI to force fallback
            original_key = os.environ.get("OPENAI_API_KEY")
            os.environ["OPENAI_API_KEY"] = "fake-key-to-force-fallback"
            
            fallback_result = run_skill(skill_name, state)
            execution_time = time.time() - start_time
            
            # Restore original key
            if original_key:
                os.environ["OPENAI_API_KEY"] = original_key
            else:
                del os.environ["OPENAI_API_KEY"]
            
            results["fallback_result"] = {
                "output": fallback_result,
                "execution_time_seconds": execution_time,
                "llm_fallback": fallback_result.get("llm_fallback", False),
                "error": fallback_result.get("error"),
                "success": "error" not in fallback_result
            }
            
            logger.info(f"Fallback version completed in {execution_time:.2f}s")
            
        except Exception as e:
            logger.error(f"Fallback version failed: {e}")
            results["fallback_result"] = {
                "output": None,
                "execution_time_seconds": time.time() - start_time,
                "error": str(e),
                "success": False
            }
    
    # Compare outputs
    if results["llm_result"] and results["fallback_result"]:
        results["comparison"] = compare_outputs(
            results["llm_result"]["output"],
            results["fallback_result"]["output"]
        )
    
    return results


def compare_outputs(llm_output: Dict[str, Any], fallback_output: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compare LLM vs deterministic outputs.
    
    Args:
        llm_output: LLM skill output
        fallback_output: Deterministic fallback output
    
    Returns:
        Comparison metrics
    """
    comparison = {
        "grounded_metrics_match": False,
        "health_status_match": False,
        "metrics_differences": [],
        "qualitative_differences": []
    }
    
    # Compare grounded metrics
    llm_metrics = llm_output.get("grounded_metrics", {})
    fallback_metrics = fallback_output.get("grounded_metrics", {})
    
    # Check health status
    llm_status = llm_metrics.get("health_status") or llm_output.get("health_status")
    fallback_status = fallback_metrics.get("health_status") or fallback_output.get("health_status")
    comparison["health_status_match"] = llm_status == fallback_status
    
    if not comparison["health_status_match"]:
        comparison["metrics_differences"].append({
            "metric": "health_status",
            "llm_value": llm_status,
            "fallback_value": fallback_status
        })
    
    # Compare numerical metrics
    if "customer_performance" in llm_metrics and "customer_performance" in fallback_metrics:
        llm_perf = llm_metrics["customer_performance"]
        fallback_perf = fallback_metrics["customer_performance"]
        
        for metric in ["total_shipments", "avg_ctd", "delay_rate_pct", "on_time_rate_pct"]:
            llm_val = llm_perf.get(metric)
            fallback_val = fallback_perf.get(metric)
            
            if llm_val is not None and fallback_val is not None:
                # Allow 5% difference for percentages, 0.5 for CTD
                tolerance = 5 if "pct" in metric else 0.5
                diff = abs(llm_val - fallback_val)
                
                if diff > tolerance:
                    comparison["metrics_differences"].append({
                        "metric": metric,
                        "llm_value": llm_val,
                        "fallback_value": fallback_val,
                        "difference": diff
                    })
    
    # Compare qualitative observations
    llm_analysis = llm_output.get("continued_analysis", "")
    fallback_analysis = fallback_output.get("continued_analysis", "")
    
    if len(llm_analysis) > len(fallback_analysis) * 1.5:
        comparison["qualitative_differences"].append(
            f"LLM provides more detailed analysis ({len(llm_analysis)} vs {len(fallback_analysis)} chars)"
        )
    
    # Overall match
    comparison["grounded_metrics_match"] = len(comparison["metrics_differences"]) == 0
    
    return comparison


def print_results(results: Dict[str, Any]):
    """Print test results in readable format."""
    print("\n" + "="*80)
    print(f"Test Results: {results['skill_name']}")
    print(f"Customer: {results['customer_id']}")
    print(f"Timestamp: {results['timestamp']}")
    print("="*80)
    
    # LLM Results
    if results["llm_result"]:
        llm_r = results["llm_result"]
        print("\n📊 LLM Version:")
        print(f"  Success: {'✅' if llm_r['success'] else '❌'}")
        print(f"  Execution Time: {llm_r['execution_time_seconds']:.2f}s")
        print(f"  LLM Used: {llm_r.get('llm_used', 'N/A')}")
        if llm_r.get("error"):
            print(f"  Error: {llm_r['error']}")
        else:
            output = llm_r["output"]
            health = output.get("grounded_metrics", {}).get("health_status") or output.get("health_status")
            print(f"  Health Status: {health}")
    
    # Fallback Results
    if results["fallback_result"]:
        fallback_r = results["fallback_result"]
        print("\n⚙️  Deterministic Fallback:")
        print(f"  Success: {'✅' if fallback_r['success'] else '❌'}")
        print(f"  Execution Time: {fallback_r['execution_time_seconds']:.2f}s")
        print(f"  LLM Fallback: {fallback_r.get('llm_fallback', 'N/A')}")
        if fallback_r.get("error"):
            print(f"  Error: {fallback_r['error']}")
        else:
            output = fallback_r["output"]
            health = output.get("grounded_metrics", {}).get("health_status") or output.get("health_status")
            print(f"  Health Status: {health}")
    
    # Comparison
    if results["comparison"]:
        comp = results["comparison"]
        print("\n🔍 Comparison:")
        print(f"  Grounded Metrics Match: {'✅' if comp['grounded_metrics_match'] else '❌'}")
        print(f"  Health Status Match: {'✅' if comp['health_status_match'] else '❌'}")
        
        if comp["metrics_differences"]:
            print("\n  Metric Differences:")
            for diff in comp["metrics_differences"]:
                print(f"    - {diff['metric']}: LLM={diff['llm_value']}, Fallback={diff['fallback_value']}")
        
        if comp["qualitative_differences"]:
            print("\n  Qualitative Differences:")
            for diff in comp["qualitative_differences"]:
                print(f"    - {diff}")
    
    print("\n" + "="*80)


def save_results(results: Dict[str, Any], output_dir: str = "test_results"):
    """Save test results to JSON file."""
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"{output_dir}/{results['skill_name']}_{results['customer_id']}_{timestamp}.json"
    
    with open(filename, "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    logger.info(f"Results saved to {filename}")
    print(f"\n💾 Results saved to: {filename}")


def main():
    parser = argparse.ArgumentParser(description="Test LLM skills vs deterministic baseline")
    parser.add_argument("--customer-id", type=str, default="6180005", help="Customer ID to test")
    parser.add_argument("--skill", type=str, default="shipment_health_check", help="Skill name to test")
    parser.add_argument("--all-skills", action="store_true", help="Test all converted skills")
    parser.add_argument("--llm-only", action="store_true", help="Test only LLM version")
    parser.add_argument("--fallback-only", action="store_true", help="Test only fallback version")
    parser.add_argument("--output-dir", type=str, default="test_results", help="Output directory for results")
    
    args = parser.parse_args()
    
    # Initialize S3 client
    settings = get_settings()
    s3_client = S3Client(bucket=settings.s3.bucket, region=settings.s3.region)
    
    # Load customer data
    try:
        state = load_customer_data(args.customer_id, s3_client)
    except Exception as e:
        logger.error(f"Failed to load customer data: {e}")
        print(f"❌ Error: Could not load data for customer {args.customer_id}")
        print(f"   {str(e)}")
        return 1
    
    # Determine which skills to test
    skills_to_test = []
    if args.all_skills:
        # List of converted skills
        skills_to_test = ["shipment_health_check"]  # Add more as converted
    else:
        skills_to_test = [args.skill]
    
    # Run tests
    all_results = []
    for skill_name in skills_to_test:
        print(f"\n🧪 Testing skill: {skill_name}")
        
        results = run_skill_test(
            skill_name=skill_name,
            state=state,
            test_llm=not args.fallback_only,
            test_fallback=not args.llm_only
        )
        
        print_results(results)
        save_results(results, args.output_dir)
        all_results.append(results)
    
    # Summary
    if len(all_results) > 1:
        print("\n" + "="*80)
        print("📊 SUMMARY")
        print("="*80)
        for r in all_results:
            llm_success = r.get("llm_result", {}).get("success", False)
            fallback_success = r.get("fallback_result", {}).get("success", False)
            match = r.get("comparison", {}).get("health_status_match", False)
            
            status = "✅" if (llm_success and match) else "⚠️" if llm_success else "❌"
            print(f"  {status} {r['skill_name']}: LLM={llm_success}, Fallback={fallback_success}, Match={match}")
    
    return 0


if __name__ == "__main__":
    exit(main())
