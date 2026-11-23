from unittest.mock import patch

import agent


def test_sonnet_55_uses_medium_effort_without_changing_output_limit():
    with patch.object(agent, 'MODEL', 'claude-sonnet-5-5'), patch.object(agent, 'SONNET_55_EFFORT', 'medium'):
        result = agent._stream_kwargs('test', [], True)
        assert result['max_tokens'] == agent.MAX_TOKENS
        assert result['thinking'] == {'type': 'adaptive'}
        assert result['output_config'] == {'effort': 'medium'}
        assert agent._stream_kwargs('test', [], False)['thinking'] == {'type': 'between_tools'}


def test_other_models_do_not_receive_sonnet_55_specific_options():
    with patch.object(agent, 'MODEL', 'claude-sonnet-4-6'):
        result = agent._stream_kwargs('test', [], False)
        assert 'output_config' not in result
        assert 'thinking' not in result
