#!/bin/sh
# Применяет DOF-набор к движку в контейнере freeciv-web и ставит бинарь.
#
#   sh deploy/freeciv-dof/apply.sh            # применить и пересобрать
#   sh deploy/freeciv-dof/apply.sh --no-install   # только пересобрать
#
# Исходники правленых файлов лежат в work/, новые файлы — в src/.
# Политика по умолчанию остаётся "none": живой стенд ведёт себя как раньше.
set -e
C=freeciv-web
SRC=/docker/freeciv/freeciv
HERE=$(cd "$(dirname "$0")" && pwd)

cp_pairs="
src/dofpolicy.c ai/default/dofpolicy.c
src/dofpolicy.h ai/default/dofpolicy.h
work/daidiplomacy.c ai/default/daidiplomacy.c
work/daiactions.c ai/default/daiactions.c
work/daisettler.c ai/default/daisettler.c
work/daiunit.h ai/default/daiunit.h
work/classicai.c ai/classic/classicai.c
work/daiunit.c ai/default/daiunit.c
work/aiiface.c server/aiiface.c
work/srv_main.c server/srv_main.c
work/plrhand.c server/plrhand.c
work/unithand.c server/unithand.c
work/meson.build meson.build
"

echo "$cp_pairs" | while read -r from to; do
  [ -n "$from" ] || continue
  docker cp "$HERE/$from" "$C:$SRC/$to"
done

docker exec -u 0 "$C" chown -R docker:docker "$SRC/ai" "$SRC/server" "$SRC/meson.build"
docker exec "$C" sh -lc "cd $SRC/../build && ninja freeciv-web" | tail -3

if [ "$1" != "--no-install" ]; then
  # Замена через mv: движок может быть запущен, перезапись «на месте» даёт ETXTBSY.
  docker exec -u 0 "$C" sh -lc '
    B=/home/docker/freeciv/bin/freeciv-web
    [ -f $B.orig ] || cp $B $B.orig
    cp /docker/freeciv/build/freeciv-web $B.new
    chmod 755 $B.new
    mv -f $B.new $B
    md5sum $B /docker/freeciv/build/freeciv-web'
  echo "Перезапустить стенд, чтобы живущие движки взяли новый бинарь:"
  echo "  docker restart $C"
fi
