#!/usr/bin/env python3
"""Tests for routing.py — triage result to dispatch decision mapping."""

import json
import os
import sys
from unittest.mock import patch, MagicMock

# Add parent directory to path for imports
scripts_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, scripts_dir)
sys.path.insert(0, os.path.join(scripts_dir, '..', 'scripts'))

import pytest

# Import the module under test (will be mocked later)
from routing import (
    route,
    cached_classify,
    COST_TIERS,
    ROUTING_TABLE,
    log_pipeline_event,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def base_triage_result():
    """Return a minimal valid triage result."""
    return {
        'category': 'general_chat',
        'confidence': 'high',
        'raw_output': 'hello',
    }


# ── Test Routing Table (10 categories) ────────────────────────────────────────

def test_routing_query_model(base_triage_result):
    """Test query_model category routes to ask skill."""
    base_triage_result['category'] = 'query_model'
    decision = route(base_triage_result)
    
    assert decision['skill'] == 'ask'
    assert decision['toolsets'] == 'file,web'
    assert decision['role'] is None


def test_routing_build_code(base_triage_result):
    """Test build_code category routes to dev skill."""
    base_triage_result['category'] = 'build_code'
    decision = route(base_triage_result)
    
    assert decision['skill'] == 'dev'
    assert decision['toolsets'] == 'file,web,terminal'
    assert decision['role'] is None


def test_routing_debug_code(base_triage_result):
    """Test debug_code category routes to dev skill with debugger role."""
    base_triage_result['category'] = 'debug_code'
    decision = route(base_triage_result)
    
    assert decision['skill'] == 'dev'
    assert decision['toolsets'] == 'file,web,terminal'
    assert decision['role'] == 'debugger'


def test_routing_research_info(base_triage_result):
    """Test research_info category routes to advisors skill."""
    base_triage_result['category'] = 'research_info'
    decision = route(base_triage_result)
    
    assert decision['skill'] == 'advisors'
    assert decision['toolsets'] == 'file,web'
    assert decision['role'] is None


def test_routing_urgent_action(base_triage_result):
    """Test urgent_action category returns None skill (inline response)."""
    base_triage_result['category'] = 'urgent_action'
    decision = route(base_triage_result)
    
    assert decision['skill'] is None
    assert decision['toolsets'] is None
    assert decision['role'] is None


def test_routing_general_chat(base_triage_result):
    """Test general_chat category returns None skill (inline response)."""
    base_triage_result['category'] = 'general_chat'
    decision = route(base_triage_result)
    
    assert decision['skill'] is None
    assert decision['toolsets'] is None
    assert decision['role'] is None


def test_routing_deploy_code(base_triage_result):
    """Test deploy_code category routes to dev skill."""
    base_triage_result['category'] = 'deploy_code'
    decision = route(base_triage_result)
    
    assert decision['skill'] == 'dev'
    assert decision['toolsets'] == 'file,web,terminal'
    assert decision['role'] is None


def test_routing_write_docs(base_triage_result):
    """Test write_docs category routes to dev skill."""
    base_triage_result['category'] = 'write_docs'
    decision = route(base_triage_result)
    
    assert decision['skill'] == 'dev'
    assert decision['toolsets'] == 'file,web'
    assert decision['role'] is None


def test_routing_status_check(base_triage_result):
    """Test status_check category returns None skill (inline response)."""
    base_triage_result['category'] = 'status_check'
    decision = route(base_triage_result)
    
    assert decision['skill'] is None
    assert decision['toolsets'] is None
    assert decision['role'] is None


def test_routing_explain_concept(base_triage_result):
    """Test explain_concept category routes to ask skill."""
    base_triage_result['category'] = 'explain_concept'
    decision = route(base_triage_result)
    
    assert decision['skill'] == 'ask'
    assert decision['toolsets'] == 'file,web'
    assert decision['role'] is None


def test_routing_config_change(base_triage_result):
    """Test config_change category routes to dev skill."""
    base_triage_result['category'] = 'config_change'
    decision = route(base_triage_result)
    
    assert decision['skill'] == 'dev'
    assert decision['toolsets'] == 'file,terminal'
    assert decision['role'] is None


def test_routing_unknown_category_raises():
    """Test unknown category raises ValueError."""
    result = {'category': 'unknown_cat', 'confidence': 'high'}
    
    with pytest.raises(ValueError, match="Unknown triage category"):
        route(result)


# ── Test Cost-Aware Model Selection ──────────────────────────────────────────

def test_cost_free_prefers_local_models(base_triage_result):
    """Test free budget prefers local models (fast, qwen, gemma)."""
    base_triage_result['category'] = 'debug_code'  # Use a skill that needs thinking
    user_context = {'cost_budget': 'free'}
    
    decision = route(base_triage_result, user_context=user_context)
    
    # Free budget should prefer local models
    model = decision['model']
    assert any(local in model for local in ['fast', 'qwen', 'gemma']), \
        f"Free budget should use local model, got: {model}"


def test_cost_low_prefers_cheap_cloud(base_triage_result):
    """Test low budget prefers cheap cloud models (glm, kimi)."""
    base_triage_result['category'] = 'debug_code'
    user_context = {'cost_budget': 'low'}
    
    decision = route(base_triage_result, user_context=user_context)
    
    # Low budget should prefer glm/kimi
    model = decision['model']
    assert any(cheap in model for cheap in ['glm', 'kimi']), \
        f"Low budget should use cheap cloud model, got: {model}"


def test_cost_medium_default_behavior(base_triage_result):
    """Test medium budget uses mid-tier models."""
    base_triage_result['category'] = 'debug_code'
    user_context = {'cost_budget': 'medium'}
    
    decision = route(base_triage_result, user_context=user_context)
    
    model = decision['model']
    # Medium should include deepseek or minimax
    assert any(mid in model for mid in ['deepseek', 'minimax']), \
        f"Medium budget should use mid-tier model, got: {model}"


def test_system_state_available_models_override(base_triage_result):
    """Test system_state available_models can constrain model selection."""
    base_triage_result['category'] = 'debug_code'
    
    # Only allow specific models
    system_state = {'available_models': ['gemma4:12b-mlx-bf16', 'glm-5.2:cloud']}
    user_context = {'cost_budget': 'high'}  # High would normally pick deepseek
    
    decision = route(base_triage_result, user_context=user_context,
                     system_state=system_state)
    
    # Should pick from available_models even if budget is high
    assert decision['model'] in ['gemma4:12b-mlx-bf16', 'glm-5.2:cloud']


# ── Test Cached Classify ─────────────────────────────────────────────────────

def test_cached_classify_returns_result():
    """Test cached_classify returns a valid triage result."""
    with patch('routing.triage.classify') as mock_classify:
        expected = {
            'category': 'build_code',
            'confidence': 'high',
            'raw_output': 'build code',
            'tokens': 5,
            'elapsed': 0.3,
        }
        mock_classify.return_value = expected
        
        # Clear cache first
        cached_classify.cache_clear()
        
        result = cached_classify("Build a REST API")
        
        assert result == expected
        # First call calls triage.classify()
        mock_classify.assert_called_once()


def test_cached_classify_uses_lru_cache():
    """Test same message returns cached result on second call."""
    with patch('routing.triage.classify') as mock_classify:
        expected = {
            'category': 'query_model',
            'confidence': 'high',
            'raw_output': 'ask deepseek',
            'tokens': 3,
            'elapsed': 0.2,
        }
        mock_classify.return_value = expected
        
        # Clear cache first
        cached_classify.cache_clear()
        
        # First call
        result1 = cached_classify("What is ACID?")
        
        # Second call with same args should NOT re-call triage.classify()
        result2 = cached_classify("What is ACID?")
        
        assert result1 == result2
        mock_classify.assert_called_once()  # Only called once due to cache


def test_cached_classify_different_messages_separate_cache():
    """Test different messages are not cached together."""
    with patch('routing.triage.classify') as mock_classify:
        results = [
            {'category': 'query_model', 'confidence': 'high'},
            {'category': 'general_chat', 'confidence': 'low'},
        ]
        mock_classify.side_effect = results
        
        # Clear cache first
        cached_classify.cache_clear()
        
        # Call twice with different messages
        result1 = cached_classify("Ask deepseek about ACID")
        result2 = cached_classify("hello")
        
        assert result1['category'] == 'query_model'
        assert result2['category'] == 'general_chat'
        assert mock_classify.call_count == 2  # Two separate cache entries


# ── Test Pipeline Event Logging ─────────────────────────────────────────────

def test_log_pipeline_event_writes_file(base_triage_result, tmp_path):
    """Test log_pipeline_event writes to jsonl file."""
    # Redirect events file to tempdir
    import routing
    original_expanduser = os.path.expanduser
    
    def mock_expanduser(path):
        if path == '~/.hermes/pipeline-events.jsonl':
            return str(tmp_path / 'pipeline-events.jsonl')
        return original_expanduser(path)
    
    with patch('os.path.expanduser', side_effect=mock_expanduser):
        routing_decision = {
            'skill': 'dev',
            'model': 'gemma4:12b-mlx-bf16',
            'thinking': 'low',
            'toolsets': 'file,web,terminal',
            'role': None,
        }
        
        log_pipeline_event(
            triage_result=base_triage_result,
            routing_decision=routing_decision,
            model_used='gemma4:12b-mlx-bf16',
            latency=0.5,
            token_count=100,
            success=True,
        )
        
        events_file = tmp_path / 'pipeline-events.jsonl'
        assert events_file.exists()
        
        # Verify JSON line format
        with open(events_file) as f:
            line = f.readline().strip()
            event = json.loads(line)
            
            assert event['triage_category'] == 'general_chat'
            assert event['routed_to'] == 'dev'
            assert event['model'] == 'gemma4:12b-mlx-bf16'
            assert event['success'] is True
            assert 'timestamp' in event


def test_log_pipeline_event_handles_failure(base_triage_result, tmp_path):
    """Test log_pipeline_event logs failure correctly."""
    import routing
    
    def mock_expanduser(path):
        if path == '~/.hermes/pipeline-events.jsonl':
            return str(tmp_path / 'pipeline-events.jsonl')
        return original_expanduser(path)
    
    # Temporarily patch expanduser
    original_expanduser = os.path.expanduser
    with patch('os.path.expanduser', side_effect=mock_expanduser):
        routing_decision = {'skill': None}
        
        log_pipeline_event(
            triage_result=base_triage_result,
            routing_decision=routing_decision,
            model_used='fast',
            latency=0.1,
            token_count=50,
            success=False,  # Failed event
        )
        
        with open(tmp_path / 'pipeline-events.jsonl') as f:
            line = json.loads(f.readline().strip())
            assert line['success'] is False


# ── Test COST_TIERS Constants ────────────────────────────────────────────────

def test_cost_tiers_structure():
    """Test COST_TIERS has correct structure."""
    assert 'free' in COST_TIERS
    assert 'low' in COST_TIERS
    assert 'medium' in COST_TIERS
    assert 'high' in COST_TIERS
    
    # Verify local models for free tier
    assert set(COST_TIERS['free']) == {'fast', 'qwen', 'gemma'}
    
    # Verify cheap cloud for low tier
    assert set(COST_TIERS['low']) == {'glm', 'kimi'}
    
    # Verify mid-tier models
    assert set(COST_TIERS['medium']) == {'deepseek', 'minimax'}


# ── Test ROUTING_TABLE Structure ─────────────────────────────────────────────

def test_routing_table_has_all_categories():
    """Test ROUTING_TABLE covers all 11 categories."""
    required = {'query_model', 'build_code', 'debug_code',
                'research_info', 'urgent_action', 'general_chat',
                'deploy_code', 'write_docs', 'config_change',
                'status_check', 'explain_concept'}
    assert set(ROUTING_TABLE.keys()) == required


def test_routing_table_consistent_structure():
    """Test ROUTING_TABLE entries have consistent structure."""
    for category, config in ROUTING_TABLE.items():
        assert 'skill' in config
        assert 'toolsets' in config
        assert 'role' in config
