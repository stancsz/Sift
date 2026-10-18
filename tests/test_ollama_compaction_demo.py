from examples.ollama_compaction_demo import answers_buried_setting


def test_demo_requires_approved_and_previous_probe_values_with_reason():
    answer = (
        "The operator approved initialDelaySeconds=25 after the readiness probe "
        "was configured with initialDelaySeconds=5."
    )

    assert answers_buried_setting(answer)


def test_demo_rejects_a_partial_answer_even_if_it_names_approved_value():
    assert not answers_buried_setting("initialDelaySeconds=25")
