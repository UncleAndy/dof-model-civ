#!/bin/bash

# Start Freeciv-web's dependency services.
#
# Need to start the dependency services in a different way to work with
# your set up? Create a script that starts them and put it in
# scripts/dependency-services-start.sh.


export JAVA_OPTS="-Djava.security.egd=file:/dev/urandom"
export CATALINA_HOME=/var/lib/tomcat10

# 0. mysql
# MariaDB: в этом образе нет команды `service`, а процесс называется mariadbd,
# поэтому исходная строка не поднимает базу — прокси на 7002 падает в check_user
# и партии через клиент не идут. Поднимаем mariadbd напрямую; заодно держим
# права на /tmp (без них InnoDB не создаёт временный файл и не стартует).
if ! pgrep -x mariadbd > /dev/null; then
  sudo mkdir -p /run/mysqld
  sudo chown mysql:mysql /run/mysqld
  sudo chmod 1777 /tmp
  sudo sh -c 'mariadbd-safe --user=mysql > /var/log/mariadb-start.log 2>&1 &'
  for i in $(seq 1 20); do
    pgrep -x mariadbd > /dev/null && break
    sleep 1
  done
fi

# 1. nginx
echo "Starting nginx first."

if [ "$(pidof nginx)" ]
then
  echo "nginx already running!"
  sudo nginx -s reload
else
  sudo service nginx start && \
  echo "nginx started!" && \
  sleep 1
fi

# 2. Tomcat
echo "Starting up Tomcat" && \
if service --status-all | grep -Fq 'tomcat10'; then
  sudo /usr/sbin/service tomcat10 start || echo "unable to start tomcat10 service"
else
  # It's a suid script, so will run as tomcat user
  sudo $CATALINA_HOME/bin/catalina.sh start
fi

# waiting for Tomcat to start, since it will take some time.
until `curl --output /dev/null --silent --head --fail "http://localhost:8080/"`; do
  printf ".."
  sleep 3
done

sleep 8
