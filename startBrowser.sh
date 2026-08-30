
sleep 2
firefox $(hostname -I | awk '{print $1}'):8080 &>/dev/null &
