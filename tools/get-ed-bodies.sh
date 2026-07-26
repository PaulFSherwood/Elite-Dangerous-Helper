#!/usr/bin/env bash
###
### Elite Dangerous current-system body exporter
###
### Readable terminal view:
###   ./get-ed-bodies.sh | column -t -s $'\t' | less -S
###
### Save only the current system:
###   ./get-ed-bodies.sh > current-system-bodies.tsv
###
### Add the current system to one growing TSV file:
###   ./get-ed-bodies.sh --append elite-bodies.tsv
###
### The script writes the header only when the append file is new or empty.
### Surface Slots and Orbital Slots are manual-entry columns.
###
set -euo pipefail

DIR="${ED_JOURNAL_DIR:-$HOME/.steam/debian-installation/steamapps/compatdata/359320/pfx/drive_c/users/steamuser/Saved Games/Frontier Developments/Elite Dangerous}"

APPEND_FILE=""
PRINT_HEADER=true

usage() {
    cat <<'USAGE'
Usage:
  get-ed-bodies.sh
  get-ed-bodies.sh --no-header
  get-ed-bodies.sh --append FILE.tsv

Options:
  --append FILE   Append this system to FILE. The header is added only if
                  FILE does not exist or is empty.
  --no-header     Print data rows without the TSV header.
  -h, --help      Show this help.
USAGE
}

while (($# > 0)); do
    case "$1" in
        --append)
            [[ $# -ge 2 ]] || {
                echo "Error: --append requires a filename." >&2
                exit 1
            }
            APPEND_FILE=$2
            shift 2
            ;;
        --no-header)
            PRINT_HEADER=false
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Error: Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

command -v jq >/dev/null 2>&1 || {
    echo "Error: jq is required. Install it with: sudo apt install jq" >&2
    exit 1
}

[[ -d "$DIR" ]] || {
    echo "Error: Journal directory not found:" >&2
    echo "$DIR" >&2
    exit 1
}

mapfile -d '' -t JOURNALS < <(
    find "$DIR" -maxdepth 1 -type f -name 'Journal.*.log' -print0 |
        sort -z
)

((${#JOURNALS[@]} > 0)) || {
    echo "Error: No Journal.*.log files found." >&2
    exit 1
}

stream_journals() {
    local file

    for file in "${JOURNALS[@]}"; do
        cat -- "$file"
    done
}

# Find the player’s current system from the newest relevant event.
# CarrierLocation is deliberately excluded because the carrier could be in a
# different system from the commander.
CURRENT_SYSTEM=$(
    stream_journals |
        jq -Rnc '
            reduce inputs as $line
                (null;
                 ($line | try fromjson catch null) as $event
                 | if ($event != null)
                      and ($event.SystemAddress? != null)
                      and (
                          ($event.event == "Location")
                          or ($event.event == "FSDJump")
                          or ($event.event == "CarrierJump")
                          or ($event.event == "Docked")
                          or ($event.event == "SupercruiseEntry")
                          or ($event.event == "SupercruiseExit")
                      )
                   then {
                       name: ($event.StarSystem // "Unknown system"),
                       address: $event.SystemAddress
                   }
                   else .
                   end)
        '
)

[[ "$CURRENT_SYSTEM" != "null" ]] || {
    echo "Error: Could not determine the current system." >&2
    exit 1
}

SYSTEM_NAME=$(jq -r '.name' <<<"$CURRENT_SYSTEM")
SYSTEM_ADDRESS=$(jq -r '.address' <<<"$CURRENT_SYSTEM")

echo "System: $SYSTEM_NAME" >&2

HEADER=$'Body Name\tSurface Slots\tOrbital Slots\tSystem Name\tSystem Address\tBody Type\tBody ID\tParents\tScan Time\tScan Type\tStar Type\tPlanet Class\tLandable\tDistance (LS)\tTidal Locked\tTerraform State\tMass (Earths)\tStellar Mass (Suns)\tRadius (km)\tGravity (g)\tSurface Temp (K)\tSurface Temp (C)\tAbsolute Magnitude\tAge (million years)\tLuminosity\tPressure (Pa)\tPressure (atm)\tAtmosphere\tAtmosphere Type\tAtmosphere Composition\tVolcanism\tIce %\tRock %\tMetal %\tMaterials\tRings\tSemi-major Axis (AU)\tEccentricity\tOrbital Inclination (deg)\tPeriapsis (deg)\tOrbital Period (days)\tAscending Node (deg)\tMean Anomaly (deg)\tRotation Period (days)\tAxial Tilt (deg)\tWas Discovered\tWas Mapped Before\tWas Footfalled\tDSS Mapped Now\tProbes Used\tEfficiency Target\tEfficient Mapping\tBio Signals\tGeo Signals\tHuman Signals\tGuardian Signals\tThargoid Signals\tAll Signals\tGenuses'

generate_rows() {
    stream_journals |
        jq -Rnr \
            --arg system_name "$SYSTEM_NAME" \
            --argjson address "$SYSTEM_ADDRESS" '

            def yesno($value):
                if $value == true then "Yes"
                elif $value == false then "No"
                else ""
                end;

            def round_to($number; $places):
                if $number == null then ""
                else
                    ([1, 10, 100, 1000, 10000, 100000, 1000000,
                      10000000, 100000000][$places]) as $factor
                    | (($number * $factor | round) / $factor)
                end;

            def parents_text:
                [
                    (.Parents // [])[]
                    | to_entries[0]
                    | "\(.key):\(.value)"
                ]
                | join(" > ");

            def atmosphere_text:
                [
                    (.AtmosphereComposition // [])[]
                    | "\(.Name)=\(.Percent)%"
                ]
                | join("; ");

            def materials_text:
                [
                    (.Materials // [])[]
                    | "\(.Name)=\(.Percent)%"
                ]
                | join("; ");

            def rings_text:
                [
                    (.Rings // [])[]
                    | "\(.Name // "Ring") [\(.RingClass // "Unknown"), MassMT=\(.MassMT // ""), InnerRad=\(.InnerRad // ""), OuterRad=\(.OuterRad // "")]"
                ]
                | join("; ");

            def signal_count($event; $localised_name; $journal_name):
                if $event == null then "Unknown"
                else
                    [
                        $event.Signals[]?
                        | select(
                            (.Type_Localised? == $localised_name)
                            or (.Type? == $journal_name)
                        )
                        | (.Count // 0)
                    ]
                    | add // 0
                end;

            def signals_text($event):
                if $event == null then ""
                else
                    [
                        $event.Signals[]?
                        | "\(.Type_Localised // .Type // "Unknown"):\(.Count // 0)"
                    ]
                    | join("; ")
                end;

            def genuses_text($event):
                if $event == null then ""
                else
                    [
                        $event.Genuses[]?
                        | (.Genus_Localised // .Genus // "Unknown")
                    ]
                    | unique
                    | join("; ")
                end;

            reduce inputs as $line
                (
                    {
                        scans: {},
                        signals: {},
                        maps: {}
                    };

                    ($line | try fromjson catch null) as $event

                    | if ($event == null)
                         or ($event.SystemAddress? != $address)
                      then .

                      # Include both planets/moons and stars.
                      elif ($event.event == "Scan")
                           and ($event.BodyID? != null)
                           and (
                               ($event.PlanetClass? != null)
                               or ($event.StarType? != null)
                           )
                      then
                          .scans[($event.BodyID | tostring)] = $event

                      elif (
                               ($event.event == "FSSBodySignals")
                               or ($event.event == "SAASignalsFound")
                           )
                           and ($event.BodyID? != null)
                      then
                          .signals[($event.BodyID | tostring)] =
                              ((.signals[($event.BodyID | tostring)] // {}) * $event)

                      elif ($event.event == "SAAScanComplete")
                           and ($event.BodyID? != null)
                      then
                          .maps[($event.BodyID | tostring)] = $event

                      else .
                      end
                )

            | . as $data

            | [
                $data.scans
                | to_entries[]
                | .key as $body_id
                | .value as $scan
                | ($data.signals[$body_id] // null) as $signal
                | ($data.maps[$body_id] // null) as $map
                | ($scan.StarType? != null) as $is_star
                | {
                    body_id: ($body_id | tonumber),

                    columns: [
                        ($scan.BodyName // ""),

                        # Manual surface construction slots. Stars and
                        # non-landable planets cannot have surface sites.
                        (
                            if $is_star or ($scan.Landable == false)
                            then "N/A"
                            else ""
                            end
                        ),

                        # Manual orbital construction slots.
                        "",

                        ($scan.StarSystem // $system_name),
                        ($scan.SystemAddress // $address),
                        (if $is_star then "Star" else "Planet" end),
                        ($scan.BodyID // ""),
                        ($scan | parents_text),
                        ($scan.timestamp // ""),
                        ($scan.ScanType // ""),
                        ($scan.StarType // ""),
                        ($scan.PlanetClass // ""),
                        (if $is_star then "N/A" else yesno($scan.Landable) end),

                        round_to($scan.DistanceFromArrivalLS?; 3),
                        (if $is_star then "" else yesno($scan.TidalLock) end),

                        (
                            if $is_star then ""
                            elif (($scan.TerraformState // "") == "") then "None"
                            else $scan.TerraformState
                            end
                        ),

                        round_to($scan.MassEM?; 6),
                        round_to($scan.StellarMass?; 6),

                        # Radius is metres; convert to kilometres.
                        (
                            if $scan.Radius? != null
                            then round_to(($scan.Radius / 1000); 2)
                            else ""
                            end
                        ),

                        # SurfaceGravity is m/s²; convert to Earth gravity.
                        (
                            if $scan.SurfaceGravity? != null
                            then round_to(($scan.SurfaceGravity / 9.80665); 4)
                            else ""
                            end
                        ),

                        round_to($scan.SurfaceTemperature?; 2),

                        (
                            if $scan.SurfaceTemperature? != null
                            then round_to(($scan.SurfaceTemperature - 273.15); 2)
                            else ""
                            end
                        ),

                        round_to($scan.AbsoluteMagnitude?; 6),
                        ($scan.Age_MY // ""),
                        ($scan.Luminosity // ""),
                        round_to($scan.SurfacePressure?; 3),

                        (
                            if $scan.SurfacePressure? != null
                            then round_to(($scan.SurfacePressure / 101325); 6)
                            else ""
                            end
                        ),

                        (
                            if $is_star then ""
                            elif (($scan.Atmosphere // "") == "") then "None"
                            else $scan.Atmosphere
                            end
                        ),

                        (
                            if $is_star then ""
                            elif (($scan.AtmosphereType // "") == "") then "None"
                            else $scan.AtmosphereType
                            end
                        ),

                        ($scan | atmosphere_text),

                        (
                            if $is_star then ""
                            elif (($scan.Volcanism // "") == "") then "None"
                            else $scan.Volcanism
                            end
                        ),

                        (
                            if $scan.Composition.Ice? != null
                            then round_to(($scan.Composition.Ice * 100); 4)
                            else ""
                            end
                        ),

                        (
                            if $scan.Composition.Rock? != null
                            then round_to(($scan.Composition.Rock * 100); 4)
                            else ""
                            end
                        ),

                        (
                            if $scan.Composition.Metal? != null
                            then round_to(($scan.Composition.Metal * 100); 4)
                            else ""
                            end
                        ),

                        ($scan | materials_text),
                        ($scan | rings_text),

                        # SemiMajorAxis is metres; convert to AU.
                        (
                            if $scan.SemiMajorAxis? != null
                            then round_to(($scan.SemiMajorAxis / 149597870700); 6)
                            else ""
                            end
                        ),

                        round_to($scan.Eccentricity?; 8),
                        round_to($scan.OrbitalInclination?; 4),
                        round_to($scan.Periapsis?; 4),

                        # OrbitalPeriod is seconds; convert to days.
                        (
                            if $scan.OrbitalPeriod? != null
                            then round_to(($scan.OrbitalPeriod / 86400); 6)
                            else ""
                            end
                        ),

                        round_to($scan.AscendingNode?; 4),
                        round_to($scan.MeanAnomaly?; 4),

                        # RotationPeriod is seconds; convert to days.
                        (
                            if $scan.RotationPeriod? != null
                            then round_to(($scan.RotationPeriod / 86400); 6)
                            else ""
                            end
                        ),

                        # AxialTilt is radians; convert to degrees.
                        (
                            if $scan.AxialTilt? != null
                            then round_to(($scan.AxialTilt * 180 / 3.141592653589793); 4)
                            else ""
                            end
                        ),

                        yesno($scan.WasDiscovered),
                        yesno($scan.WasMapped),
                        (if $is_star then "N/A" else yesno($scan.WasFootfalled) end),
                        (if $is_star then "N/A" elif $map == null then "No" else "Yes" end),
                        ($map.ProbesUsed // ""),
                        ($map.EfficiencyTarget // ""),

                        (
                            if ($map != null)
                               and ($map.ProbesUsed? != null)
                               and ($map.EfficiencyTarget? != null)
                            then
                                if $map.ProbesUsed <= $map.EfficiencyTarget
                                then "Yes"
                                else "No"
                                end
                            else ""
                            end
                        ),

                        (if $is_star then "" else signal_count($signal; "Biological"; "$SAA_SignalType_Biological;") end),
                        (if $is_star then "" else signal_count($signal; "Geological"; "$SAA_SignalType_Geological;") end),
                        (if $is_star then "" else signal_count($signal; "Human"; "$SAA_SignalType_Human;") end),
                        (if $is_star then "" else signal_count($signal; "Guardian"; "$SAA_SignalType_Guardian;") end),
                        (if $is_star then "" else signal_count($signal; "Thargoid"; "$SAA_SignalType_Thargoid;") end),
                        (if $is_star then "" else signals_text($signal) end),
                        (if $is_star then "" else genuses_text($signal) end)
                    ]
                }
            ]

            | sort_by(.body_id)
            | .[]
            | .columns
            | @tsv
        '
}

write_tsv() {
    if [[ "$PRINT_HEADER" == true ]]; then
        printf '%s\n' "$HEADER"
    fi

    generate_rows
}

if [[ -n "$APPEND_FILE" ]]; then
    mkdir -p -- "$(dirname -- "$APPEND_FILE")"

    if [[ -s "$APPEND_FILE" ]]; then
        PRINT_HEADER=false
    else
        PRINT_HEADER=true
    fi

    write_tsv >> "$APPEND_FILE"
    echo "Added $SYSTEM_NAME to: $APPEND_FILE" >&2
else
    write_tsv
fi

