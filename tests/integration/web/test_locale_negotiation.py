"""Taalkeuze: browsertaal (Accept-Language), expliciete keuze, taalkiezer en vertaalde meldingen."""

from __future__ import annotations

import re

import pytest

from tests.fixtures.auth import ADMIN_PASSWORD, ADMIN_USER
from tests.integration.web.conftest import create_vehicle, csrf_from
from wisselweer.i18n import LOCALE_NAMES, SUPPORTED_LOCALES, negotiate_locale


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, "nl-NL"),
        ("", "nl-NL"),
        ("nl", "nl-NL"),
        ("nl-NL", "nl-NL"),
        ("nl-BE", "nl-BE"),
        ("nl-be", "nl-BE"),
        ("nl_BE", "nl-BE"),
        ("nl-SR", "nl-NL"),  # overige nl* -> nl-NL
        ("en", "en"),
        ("en-GB,en;q=0.9", "en"),
        ("en-US", "en"),
        ("de", "de-DE"),
        ("de-AT,de;q=0.8", "de-DE"),
        ("DE-ch", "de-DE"),
        ("fr-FR,fr;q=0.9", "nl-NL"),  # niets bekends: standaard
        ("*", "nl-NL"),
        ("garbage;;;==,,", "nl-NL"),
        # q-waarden bepalen de volgorde, niet de positie in de header
        ("de;q=0.5, en;q=0.9", "en"),
        ("nl;q=0.3, de;q=0.8, en;q=0.7", "de-DE"),
        ("en;q=0.8, de;q=0.8", "en"),  # gelijke q: eerste wint
        # onbekende talen overslaan, de eerstvolgende bekende pakken
        ("fr, en;q=0.5", "en"),
        ("fr, ja;q=0.9, de;q=0.1", "de-DE"),
        # q=0 betekent "niet gewenst"; ongeldige q telt als niet gewenst
        ("en;q=0, de", "de-DE"),
        ("en;q=abc, de;q=0.1", "de-DE"),
        ("nl-BE, nl;q=0.8, en;q=0.7", "nl-BE"),
        ("nl;q=0.8, nl-BE;q=0.9", "nl-BE"),
        ("en;q=5, nl;q=1", "en"),  # q > 1 wordt op 1 gezet; gelijk: eerste wint
    ],
)
def test_negotiate_locale(header, expected):
    assert negotiate_locale(header) == expected


def test_negotiate_locale_survives_absurd_input():
    assert negotiate_locale("," * 10_000) == "nl-NL"
    assert negotiate_locale("x;q=" + "9" * 10_000) == "nl-NL"
    # alleen de eerste tekens/items tellen: een bekende taal ver achteraan wordt genegeerd
    assert negotiate_locale("xx," * 100 + "de") == "nl-NL"


# --- loginpagina (zonder sessie) -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "lang_attr", "title"),
    [
        ("en-GB,en;q=0.9,nl;q=0.5", "en", "Log in"),
        ("de-DE,de;q=0.9", "de-DE", "Anmelden"),
        ("nl-BE,nl;q=0.8", "nl-BE", "Inloggen"),
        ("nl-NL", "nl-NL", "Inloggen"),
        ("fr-FR", "nl-NL", "Inloggen"),
        (None, "nl-NL", "Inloggen"),
    ],
)
def test_login_page_follows_accept_language(anon, header, lang_attr, title):
    headers = {"Accept-Language": header} if header else {}
    html = anon.get("/login", headers=headers).text
    assert f'<html lang="{lang_attr}"' in html
    assert f"<h1>{title}</h1>" in html


def test_login_page_has_no_dutch_leftovers_in_english(anon):
    html = anon.get("/login", headers={"Accept-Language": "en"}).text
    for word in ("Gebruikersnaam", "Wachtwoord", "Inloggen", "Het juiste moment"):
        assert word not in html


def test_login_error_is_translated(anon):
    headers = {"Accept-Language": "en"}
    page = anon.get("/login", headers=headers)
    r = anon.post(
        "/login",
        headers=headers,
        data={
            "username": "nobody",
            "password": "wrong-password",
            "csrf_token": csrf_from(page.text),
        },
    )
    assert r.status_code == 401
    assert "Incorrect username or password" in r.text
    assert "Onjuiste" not in r.text


def test_login_explicit_choice_beats_header_and_survives_login(anon):
    headers = {"Accept-Language": "en"}
    html = anon.get("/login?lang=de-DE", headers=headers).text
    assert '<html lang="de-DE"' in html and "Anmelden" in html
    # de keuze zit in de sessie: ook zonder ?lang= en ondanks de browsertaal
    assert '<html lang="de-DE"' in anon.get("/login", headers=headers).text
    page = anon.get("/login", headers=headers)
    r = anon.post(
        "/login",
        headers=headers,
        data={
            "username": ADMIN_USER,
            "password": ADMIN_PASSWORD,
            "csrf_token": csrf_from(page.text),
            "next": "/",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    # ...en blijft na het inloggen gelden (de sessie wordt vernieuwd, de taal niet gewist)
    dash = anon.get("/", headers=headers).text
    assert '<html lang="de-DE"' in dash and "Übersicht" in dash


def test_login_language_links_keep_the_destination(anon):
    html = anon.get("/login?next=%2Fsettings").text
    assert 'href="?lang=en&amp;next=%2Fsettings"' in html


# --- ingelogd -------------------------------------------------------------------------------------


def test_dashboard_follows_accept_language_until_explicit_choice(web):
    en = {"Accept-Language": "en-GB,en;q=0.8"}
    assert '<html lang="en"' in web.get("/", headers=en).text
    assert '<html lang="de-DE"' in web.get("/", headers={"Accept-Language": "de"}).text
    assert '<html lang="nl-NL"' in web.get("/").text  # geen header: standaard
    # expliciete keuze gaat voor en blijft in de sessie staan
    assert '<html lang="nl-NL"' in web.get("/?lang=nl-NL", headers=en).text
    assert '<html lang="nl-NL"' in web.get("/", headers=en).text
    assert '<html lang="de-DE"' in web.get("/?lang=de-DE", headers=en).text
    assert '<html lang="de-DE"' in web.get("/", headers=en).text


def test_unknown_lang_param_does_not_override_browser_language(web):
    html = web.get("/?lang=xx", headers={"Accept-Language": "en"}).text
    assert '<html lang="en"' in html


def test_error_page_follows_locale(web):
    r = web.get("/vehicles/999", headers={"Accept-Language": "de"})
    assert r.status_code == 404
    assert "Diese Seite gibt es nicht (mehr)." in r.text and '<html lang="de-DE"' in r.text


def test_language_picker_shows_own_names_with_lang_attributes(web):
    html = web.get("/?lang=en").text
    footer = html.split('<p class="lang"')[1].split("</p>")[0]
    links = re.findall(r"<a ([^>]*)>([^<]*)</a>", footer)
    assert [text for _, text in links] == [LOCALE_NAMES[c] for c in SUPPORTED_LOCALES]
    assert [text for _, text in links] == [
        "Nederlands",
        "Nederlands (België)",
        "English",
        "Deutsch",
    ]
    for (attrs, _), code in zip(links, SUPPORTED_LOCALES, strict=True):
        assert f'href="?lang={code}"' in attrs
        assert f'hreflang="{code}"' in attrs
        assert f' lang="{code}"' in attrs
        assert ('aria-current="true"' in attrs) == (code == "en")
    # de namen zijn niet vertaald: in elke UI-taal hetzelfde
    for lang in SUPPORTED_LOCALES:
        again = web.get(f"/?lang={lang}").text.split('<p class="lang"')[1].split("</p>")[0]
        assert [t for _, t in re.findall(r"<a ([^>]*)>([^<]*)</a>", again)] == [
            "Nederlands",
            "Nederlands (België)",
            "English",
            "Deutsch",
        ]


# --- vertaalde meldingen en opmaak ----------------------------------------------------------------


def test_service_errors_are_shown_in_the_users_language(web):
    web.get("/?lang=en")
    assert web.post("/settings/tokens", {"token_name": "ha"}).status_code == 200
    assert web.post("/settings/tokens", {"token_name": "ha"}).status_code == 303
    page = web.c.get("/settings").text
    assert "An active token with this name already exists." in page
    assert "Er bestaat al" not in page
    web.get("/?lang=de-DE")
    web.post("/settings/tokens", {"token_name": "ha"})
    assert "Es gibt bereits ein aktives Token mit diesem Namen." in web.c.get("/settings").text


def test_form_service_error_in_english(web):
    web.get("/?lang=en")
    vid = create_vehicle(web)
    ok = web.post(f"/vehicles/{vid}/sets/new", {"type": "summer", "status": "mounted"})
    assert ok.status_code == 303
    # een tweede gemonteerde set mag niet; de melding staat in de taal van de gebruiker
    r = web.post(f"/vehicles/{vid}/sets/new", {"type": "winter", "status": "mounted"})
    assert r.status_code == 422
    assert "A set is already mounted." in r.text
    assert "Er is al een gemonteerde set" not in r.text


def test_numbers_and_prices_follow_the_language():
    from wisselweer.i18n import format_euro, format_number

    assert format_number(1234567, "nl-NL") == "1.234.567"
    assert format_number(1234567, "nl-BE") == "1.234.567"
    assert format_number(1234567, "en") == "1,234,567"
    assert format_number(1234567, "de-DE") == "1.234.567"
    assert format_number(7.5, "nl-NL", 1) == "7,5"
    assert format_number(7.5, "en", 1) == "7.5"
    assert format_number(7.5, "de-DE", 1) == "7,5"
    assert format_euro(123450, "nl-NL") == "€ 1.234,50"
    assert format_euro(123450, "en") == "€1,234.50"
    assert format_euro(123450, "de-DE") == "1.234,50 €"
    assert format_euro(None, "en") == ""
