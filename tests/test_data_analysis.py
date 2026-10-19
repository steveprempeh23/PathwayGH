import pytest

from app.tools.data_analysis import analyze_outcomes


def test_unfiltered_summary_covers_whole_dataset():
    stats = analyze_outcomes()
    assert stats.sample_size == 480  # 5 years * 8 categories * 12 students
    assert stats.min_aggregate <= stats.mean_aggregate <= stats.max_aggregate
    assert "synthetically generated" in stats.data_source


def test_filter_by_known_category_returns_expected_sample_size():
    stats = analyze_outcomes(programme_category="Medicine / Dentistry")
    assert stats.sample_size == 60  # 5 years * 12 students
    assert stats.filter_programme_category == "Medicine / Dentistry"


def test_admission_rate_by_year_covers_all_five_years():
    stats = analyze_outcomes(programme_category="Business / Finance / Accounting")
    assert set(stats.admission_rate_by_year.keys()) == {"2021", "2022", "2023", "2024", "2025"}
    for rate in stats.admission_rate_by_year.values():
        assert 0.0 <= rate <= 100.0


def test_unknown_category_raises_rather_than_returning_empty_silently():
    with pytest.raises(ValueError, match="Unknown programme_category"):
        analyze_outcomes(programme_category="Underwater Basket Weaving")


def test_track_filter_narrows_results():
    all_science = analyze_outcomes(track="science")
    medicine_only = analyze_outcomes(programme_category="Medicine / Dentistry", track="science")
    assert medicine_only.sample_size <= all_science.sample_size


def test_mean_is_a_real_computed_value_not_a_placeholder():
    """Loose sanity check that stats vary across categories - if this tool
    were accidentally returning a fixed stub value, every category would
    report an identical mean."""
    medicine = analyze_outcomes(programme_category="Medicine / Dentistry")
    hnd = analyze_outcomes(programme_category="HND / Polytechnic (Technical University) Tracks")
    assert medicine.mean_aggregate != hnd.mean_aggregate
