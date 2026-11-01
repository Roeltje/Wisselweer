# Kilometerstand uit Home Assistant

Wisselweer rekent per bandenset de gereden kilometers uit, op basis van kilometerstanden. Heeft je auto een Home Assistant-integratie met een kilometerteller (odometer-sensor), dan kun je die stand automatisch doorgeven en hoef je hem niet meer met de hand in te voeren.

Dit werkt voor elk merk waarvoor je in Home Assistant zo'n sensor hebt. Een aantal integraties die dat (soms) bieden, zonder garantie dat jouw model of abonnement de kilometerstand doorgeeft:

- Kia en Hyundai via "Kia UVO / Hyundai Bluelink" (HACS)
- Tesla
- Volkswagen
- BMW
- Renault

Kijk in Home Assistant onder Instellingen > Apparaten en diensten of er bij jouw auto een entiteit staat met als eenheid km (of mi) en een naam als "odometer" of "kilometerstand". Staat die er niet, dan kan dit niet automatisch en blijft handmatig invoeren in Wisselweer de weg.

De voorbeelden gebruiken `https://wisselweer.example.invalid` als adres van je Wisselweer; vervang dat door je eigen adres. De voorbeelden zijn niet getest tegen elke Home Assistant-versie; de YAML hieronder gebruikt de syntaxis van Home Assistant 2024.10 en nieuwer (`triggers:`, `actions:`).

## 1. API-token aanmaken

Op de server waar Wisselweer draait (zie [install-lxc.md](install-lxc.md) of [install-docker.md](install-docker.md)):

```
wisselweer create-api-token --name homeassistant
```

Het token (begint met `wwt_`) wordt één keer getoond; kopieer het meteen. Wisselweer bewaart alleen een hash. Het token geeft toegang tot de hele API, dus behandel het als een wachtwoord. Intrekken kan met `wisselweer revoke-api-token --name homeassistant`. Meer over tokens: [api.md](api.md#authenticatie).

## 2. Voertuig-id opzoeken

Het id van je voertuig staat in de API:

```
curl -H "Authorization: Bearer wwt_..." https://wisselweer.example.invalid/api/v1/vehicles
```

Zoek in het antwoord het veld `"id"` van je auto (hieronder `1`).

## 3. Token in `secrets.yaml`

Zet in `secrets.yaml` van Home Assistant de hele waarde van de header, dus inclusief het woord `Bearer`:

```yaml
wisselweer_token: "Bearer wwt_vervang_dit_door_je_token"
```

## 4. `rest_command`

In `configuration.yaml` (of een apart bestand dat je includet):

```yaml
rest_command:
  wisselweer_kilometerstand:
    url: "https://wisselweer.example.invalid/api/v1/vehicles/1/odometer"
    method: POST
    headers:
      Authorization: !secret wisselweer_token
    content_type: "application/json"
    payload: '{"reading_km": {{ km | int }}, "note": "Home Assistant"}'
    timeout: 20
```

Wisselweer verwacht in het JSON-lichaam `reading_km` (geheel getal, kilometers, 0 of hoger). Optioneel zijn `recorded_at` (tijdstip met tijdzone; standaard nu) en `note`. Bij succes antwoordt de API met status `201` en de opgeslagen stand.

Een hulpwaarde om de laatst doorgegeven stand te onthouden (Instellingen > Apparaten en diensten > Hulpmiddelen, of in YAML):

```yaml
input_number:
  wisselweer_laatste_km:
    name: Laatste kilometerstand naar Wisselweer
    min: 0
    max: 2000000
    step: 1
    mode: box
```

## 5. Wat Wisselweer weigert, en hoe de automatisering dat vermijdt

- Een **lagere** stand dan een eerdere stand wordt geweigerd met `409` en `{"detail": "invalid_operation", ...}`.
- Een **gelijke** stand wordt wel geaccepteerd, maar levert een dubbele regel in de lijst met standen op. Dat wil je niet elke keer dat de sensor ververst.
- Een negatief getal of geen getal geeft `422`.

De automatisering hieronder stuurt daarom alleen een stand door als die (a) een geldig getal in km is, (b) hoger is dan de laatst doorgegeven stand en (c) niet onwaarschijnlijk veel hoger is (sanity-conditie: hier niet meer dan 5.000 km sprong). Zo komen foutieve sensorwaarden (0, `unknown`, een reset na een firmware-update) niet in je gegevens. De trigger wacht tien minuten nadat de waarde verandert, zodat een auto die onderweg elke kilometer doorgeeft niet honderden regels aanmaakt.

```yaml
automation:
  - alias: "Wisselweer: kilometerstand doorgeven"
    mode: single
    triggers:
      - trigger: state
        entity_id: sensor.mijn_auto_odometer   # pas aan naar jouw entiteit
        not_from:
          - unknown
          - unavailable
        not_to:
          - unknown
          - unavailable
        for: "00:10:00"
    conditions:
      - condition: template
        value_template: >-
          {% set new = states('sensor.mijn_auto_odometer') | float(-1) %}
          {% set last = states('input_number.wisselweer_laatste_km') | float(0) %}
          {{ state_attr('sensor.mijn_auto_odometer', 'unit_of_measurement') == 'km'
             and new > 0
             and new > last
             and (last == 0 or new - last <= 5000) }}
    actions:
      - action: rest_command.wisselweer_kilometerstand
        continue_on_error: true
        data:
          km: "{{ states('sensor.mijn_auto_odometer') | float | round(0) | int }}"
        response_variable: wisselweer
      - if: "{{ wisselweer is defined and wisselweer.status == 201 }}"
        then:
          - action: input_number.set_value
            target:
              entity_id: input_number.wisselweer_laatste_km
            data:
              value: "{{ states('sensor.mijn_auto_odometer') | float | round(0) | int }}"
```

Notities:

- Geeft je sensor mijlen (`mi`) door, dan is de conditie op `km` bewust niet vervuld: reken dan eerst om (`* 1.609344`) in zowel de conditie als de `km`-waarde, of stel in Home Assistant de eenheden op metrisch.
- Werkt de eerste keer niets omdat de sprong naar je echte kilometerstand te groot lijkt? De hulpwaarde `wisselweer_laatste_km` staat dan op 0, en met 0 wordt de sprongcontrole overgeslagen. Staat hij al op een lagere waarde, zet hem dan eenmalig zelf op de huidige stand.
- Een mislukte aanroep (bijvoorbeeld `409` omdat je tussendoor handmatig een hogere stand invoerde) kan een melding in het logboek van Home Assistant geven. De hulpwaarde wordt dan niet bijgewerkt en de volgende wijziging probeert het opnieuw.
- Zet je Wisselweer op een ander adres of achter een reverse proxy, pas dan alleen de `url` aan. Gebruik https zodra het token over een netwerk gaat dat je niet vertrouwt.

## Controleren

Bekijk in Wisselweer bij het voertuig onder "Kilometerstanden" of de stand er staat (bron "handmatig", met de notitie "Home Assistant"), of via de API:

```
curl -H "Authorization: Bearer wwt_..." https://wisselweer.example.invalid/api/v1/vehicles/1/odometer
```

De gereden kilometers per bandenset worden berekend uit de standen bij de wissels en de laatste stand (`GET /api/v1/tire-sets/{id}/km`).
