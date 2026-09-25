import pytest

import crud
import import_time_standards as its
from conftest import FakePage, word
from models import Course, Stroke, TimeStandard

# --- pure helpers ----------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        (":58.59", 58.59),
        ("1:44.09", 104.09),
        ("36.29", 36.29),
        ("25.00*", 25.0),
        ("  12:01.50 ", 721.5),
        ("35:39", None),
        ("", None),
        ("abc", None),
    ],
)
def test_parse_time(raw, expected):
    assert its.parse_time(raw) == (pytest.approx(expected) if expected is not None else None)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Girls 11-12 Boys", "11-12"),
        ("15-16 / 17 & Over /Senior BONUS", "15-16/17 & Over/Senior"),
        ("  10  &   under ", "10 & under"),
    ],
)
def test_clean_age_group(raw, expected):
    assert its.clean_age_group(raw) == expected


def test_extract_season():
    assert its.extract_season("2024-2028 Motivational Standards") == "2024-2028"
    assert its.extract_season("no year here") == "unknown"


def test_cluster_rows_groups_by_top_with_tolerance():
    rows = its.cluster_rows([word("b", 0, 11.5), word("a", 0, 10), word("c", 0, 20)])
    assert [[w["text"] for w in r["words"]] for r in rows] == [["a", "b"], ["c"]]


def test_column_boundaries_and_bucketing():
    boundaries = its.column_boundaries([30, 10, 20])
    assert boundaries == [15, 25]
    cols = its.bucket_columns([word("z", 31, 0), word("x", 9, 0), word("y1", 18, 0), word("y2", 22, 0)], boundaries)
    assert cols == {0: "x", 1: "y1 y2", 2: "z"}


def test_import_stats_report(capsys):
    stats = its.ImportStats()
    stats.inserted, stats.duplicates, stats.events_created = 3, 2, 1
    stats.malformed.append("bad row")
    stats.report("Label")
    out = capsys.readouterr().out
    assert "--- Label ---" in out
    assert "Inserted:       3" in out
    assert "Skipped malformed values: 1" in out
    assert "- bad row" in out


def test_import_stats_report_omits_malformed_when_none(capsys):
    its.ImportStats().report("L")
    assert "malformed" not in capsys.readouterr().out


# --- USA Swimming layout ---------------------------------------------------

GIRLS_X = [10, 20, 30, 40, 50, 60]  # B BB A AA AAA AAAA
BOYS_X = [150, 160, 170, 180, 190, 200]  # AAAA AAA AA A BB B
EVENT_X = 100


def usa_pages():
    header = [word(t, x, 50) for t, x in zip(its.USA_GIRLS_ORDER, GIRLS_X)]
    header += [word("Event", EVENT_X, 50)]
    header += [word(t, x, 50) for t, x in zip(its.USA_BOYS_ORDER, BOYS_X)]

    before_header = [word("30.00", 10, 65), word("50", 100, 65), word("FR", 108, 65), word("SCY", 116, 65)]
    age_row = [word("Girls", 5, 70), word("11-12", 20, 70), word("Boys", 170, 70)]
    girls = [
        word("36.29", 10, 90),
        word("33.09", 20, 90),
        word(":29.59", 30, 90),
        # AA (x=40) intentionally blank: no standard published
        word("bad", 50, 90),
        word("25.00*", 60, 90),
    ]
    evt = [word("50", 100, 90), word("FR", 108, 90), word("SCY", 116, 90)]
    boys = [word(t, x, 90) for t, x in zip(["24.00", "25.00", "26.00", "27.00", "28.00", "1:02.00"], BOYS_X)]
    relay = [word("200", 100, 110), word("FR-R", 108, 110), word("SCY", 116, 110), word("1:50.00", 10, 110)]

    return [
        FakePage(
            header + before_header + age_row + girls + evt + boys + relay,
            text="2024-2028 Motivational Standards",
            page_number=1,
        ),
        FakePage([word("Notes", 10, 10)], page_number=2),  # no Event header
        FakePage([word("Event", 100, 200)], page_number=3),  # no tier headers near top
    ]


@pytest.fixture
def usa_pdf(fake_pdfplumber):
    fake_pdfplumber(its, {"usa.pdf": usa_pages()})
    return "usa.pdf"


def test_import_usa_standards(db, usa_pdf):
    stats = its.ImportStats()
    its.import_usa_standards(db, usa_pdf, stats)

    assert stats.inserted == 10  # 4 girls (AA blank, AAA malformed) + 6 boys
    assert stats.events_created == 1
    assert len(stats.malformed) == 2
    assert any("before any age-group header" in m for m in stats.malformed)
    assert any("Girls 50 FR SCY AAA: 'bad'" in m for m in stats.malformed)

    event = crud.get_event(db, 50, Stroke.FR, Course.SCY)
    girls_a = crud.get_time_standard(db, event.id, "USA Swimming", "11-12", "F", "A", "2024-2028")
    assert girls_a.time_seconds == pytest.approx(29.59)
    assert girls_a.standard_rank == 3
    boys_b = crud.get_time_standard(db, event.id, "USA Swimming", "11-12", "M", "B", "2024-2028")
    assert boys_b.time_seconds == pytest.approx(62.0)
    assert boys_b.standard_rank == 1
    assert crud.get_time_standard(db, event.id, "USA Swimming", "11-12", "F", "AA", "2024-2028") is None
    # relay row never becomes an event
    assert crud.get_event(db, 200, Stroke.FR, Course.SCY) is None


def test_import_usa_standards_is_idempotent(db, usa_pdf):
    its.import_usa_standards(db, usa_pdf, its.ImportStats())
    stats = its.ImportStats()
    its.import_usa_standards(db, usa_pdf, stats)
    assert (stats.inserted, stats.duplicates, stats.events_created) == (0, 10, 0)
    assert db.query(TimeStandard).count() == 10


# --- MN Swimming layout ----------------------------------------------------

MN_GIRLS_X = [10, 20, 30, 40, 50]
MN_BOYS_X = [150, 160, 170, 180, 190]


def mn_page():
    title = [word("Girls", 10, 30), word("BRNZ", 20, 30)]  # has BRNZ but also Girls: not the legend
    legend = [word(t, x, 50) for t, x in zip(its.MN_GIRLS_ORDER, MN_GIRLS_X)]
    legend += [word("Event", EVENT_X, 50)]
    legend += [word(t, x, 50) for t, x in zip(its.MN_BOYS_ORDER, MN_BOYS_X)]
    before_header = [word("40.00", 10, 60), word("100", 100, 60), word("Back", 110, 60)]
    age_row = [word("Girls", 5, 70), word("11-12", 20, 70), word("Boys", 170, 70)]
    girls = [word(t, x, 90) for t, x in zip(["35.00", "33.00", "31.00", "30.00", "29.00"], MN_GIRLS_X)]
    evt = [word("50", 100, 90), word("Free", 110, 90)]
    boys = [word(t, x, 90) for t, x in zip(["27.00", "28.00", "35:39", "30.00", "31.00"], MN_BOYS_X)]
    return FakePage(title + legend + before_header + age_row + girls + evt + boys, text="MN 2025-2026")


def test_import_mn_standards(db, fake_pdfplumber):
    fake_pdfplumber(its, {"mn.pdf": [mn_page()]})
    stats = its.ImportStats()
    its.import_mn_standards(db, "mn.pdf", Course.LCM, stats)

    assert stats.inserted == 9  # boys GOLD is malformed
    assert stats.events_created == 1
    assert len(stats.malformed) == 2
    assert any("MN LCM 100 Back: data row before" in m for m in stats.malformed)
    assert any("Boys 50 Free GOLD: '35:39'" in m for m in stats.malformed)

    event = crud.get_event(db, 50, Stroke.FR, Course.LCM)
    zone = crud.get_time_standard(db, event.id, "MN Swimming", "11-12", "M", "ZONE", "2025-2026")
    assert zone.time_seconds == pytest.approx(27.0)
    assert zone.standard_rank == 5


def test_import_mn_standards_without_legend(db, fake_pdfplumber, capsys):
    fake_pdfplumber(its, {"mn.pdf": [FakePage([word("Hello", 10, 10)])]})
    stats = its.ImportStats()
    its.import_mn_standards(db, "mn.pdf", Course.SCY, stats)
    assert "could not find the BRNZ" in capsys.readouterr().out
    assert stats.inserted == 0


def test_import_mn_standards_legend_without_event(db, fake_pdfplumber, capsys):
    fake_pdfplumber(its, {"mn.pdf": [FakePage([word("BRNZ", 10, 10), word("SLVR", 20, 10)])]})
    its.import_mn_standards(db, "mn.pdf", Course.SCY, its.ImportStats())
    assert "no 'Event' column header" in capsys.readouterr().out


# --- main ------------------------------------------------------------------


def test_main(db, session_factory, fake_pdfplumber, monkeypatch, tmp_path, capsys):
    (tmp_path / "USA_Swimming_Motivational_Standards.pdf").touch()
    (tmp_path / "MN_Swimming_SCY_Standards.pdf").touch()
    # LCM file intentionally missing
    fake_pdfplumber(
        its,
        {
            str(tmp_path / "USA_Swimming_Motivational_Standards.pdf"): usa_pages(),
            str(tmp_path / "MN_Swimming_SCY_Standards.pdf"): [mn_page()],
        },
    )
    monkeypatch.setattr(its, "STANDARDS_DIR", tmp_path)
    monkeypatch.setattr(its, "SessionLocal", session_factory)

    its.main()

    out = capsys.readouterr().out
    assert "Importing USA Swimming Motivational Standards" in out
    assert "Importing MN Swimming SCY Standards" in out
    assert "SKIPPING MN Swimming LCM Standards" in out
    assert db.query(TimeStandard).count() == 19
