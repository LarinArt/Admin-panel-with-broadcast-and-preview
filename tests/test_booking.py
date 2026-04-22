import pytest

# Тест логики распределения (как в вашей идее с 10%)
def test_winner_calculation():
    participants = 55
    # Логика: 10% от 55 = 5.5, округляем до 6
    winners_count = int((participants * 0.1) + 0.5) 
    assert winners_count == 6

# Тест на корректность работы pytest
def test_simple_check():
    assert 1 + 1 == 2