"""Tests for the controller intent classifier."""

from services import graph_qa


def test_classify_intent_recognises_definition():
    assert graph_qa._classify_intent("什么是断裂韧性？") == "definition"
    assert graph_qa._classify_intent("definition of toughness") == "definition"


def test_classify_intent_recognises_comparison():
    assert graph_qa._classify_intent("韧性 vs 硬度") == "comparison"
    assert graph_qa._classify_intent("fatigue and corrosion 的区别") == "comparison"


def test_classify_intent_recognises_mechanism():
    assert graph_qa._classify_intent("为什么会出现氢脆？") == "mechanism"
    assert graph_qa._classify_intent("how does corrosion occur") == "mechanism"


def test_classify_intent_recognises_formula():
    assert graph_qa._classify_intent("热导率的公式是什么？") == "formula"
    assert graph_qa._classify_intent("推导 Arrhenius equation") == "formula"


def test_classify_intent_recognises_application():
    assert graph_qa._classify_intent("这个原理的实际应用场景？") == "application"
    assert graph_qa._classify_intent("举个例子说明") == "application"


def test_classify_intent_falls_back_to_general():
    assert graph_qa._classify_intent("断裂") == "general"
    assert graph_qa._classify_intent("") == "general"
