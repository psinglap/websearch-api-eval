#!/usr/bin/env bash
# Start each use case's next pass >=12 min after its previous pass, never overlapping another API run.
cd "$(dirname "$0")"
last() { ls -t out/searchonly/${1}_run${2}_*.json 2>/dev/null | head -1; }
busy() { pgrep -f "promptfoo eval" >/dev/null; }
done_set=""
while :; do
  for job in "gtm 2" "insurance 2" "gtm 3" "finance 2" "insurance 3" "finance 3"; do
    set -- $job; uc=$1; n=$2; prev=$((n-1))
    case " $done_set " in *" $uc$n "*) continue;; esac
    f=$(last $uc $prev); [ -n "$f" ] || continue
    # run 1 file is written when the calls finish; for gtm/insurance run1 ensure promptfoo finished writing
    age=$(( $(date +%s) - $(stat -f %m "$f") )); [ $age -ge 720 ] || continue
    busy && continue
    ./searchonly_uc.sh $n $uc; done_set="$done_set $uc$n"
  done
  [ $(echo $done_set | wc -w) -ge 6 ] && break
  sleep 20
done
echo ALL DONE; date -u
