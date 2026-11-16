# Simulation de services TCP / UDP

Le lab **09 Services TCP/UDP** place un poste derrière un firewall transparent,
puis un switch NETGEAR 8 ports avec NAS QNAP, imprimante Brother, caméra et DNS.
Les règles autorisent DNS UDP/53, SMB TCP/445 et impression TCP/9100 ; RTSP
TCP/554 est refusé. ICMP n'est pas autorisé par défaut dans ce scénario.

```text
probe tcp nas.lan 445
probe tcp printer.lan 9100
probe tcp camera.lan 554
```

Le premier et le deuxième test réussissent ; le troisième est bloqué par la règle
40. `ping nas.lan` peut échouer alors que `probe tcp nas.lan 445` réussit : les
politiques sont distinctes par protocole et port. La résolution DNS vérifie
maintenant l'accès UDP/53 au serveur local, sans dépendre d'une autorisation ICMP.

## Services d'un endpoint

```text
show services
listen tcp 443 HTTPS
listen udp 161 SNMP
unlisten tcp 443
clear services
```

Les profils Serveur ont des ports HTTP/HTTPS par défaut, NAS SMB/445, imprimante
RAW/9100, caméra RTSP/554 et téléphone SIP UDP/5060. La configuration DNS est
indépendante : `service dns` active les sondes DNS TCP/UDP 53. Désactiver une
entrée de services ne désactive pas le DNS géré dans son propre onglet.
Les listes de ports et noms de services persistent dans JSON et export texte.

## Ce qui est calculé

Chaque test vérifie le chemin aller et retour : câbles, ports, VLANs/trunks, STP,
passerelles connectées, protections et politiques firewall. Il vérifie ensuite
qu'un service est activé sur le port visé. Les trajets et décisions apparaissent
dans la simulation et le navigateur.

C'est un modèle de transaction, pas une pile réseau réelle : pas de sockets vers
les IP virtuelles, segments SYN/ACK, numéros de séquence, retransmissions,
fragmentation, délai mesuré, débit, traitement SMB, impression, vidéo ou téléphonie.
Le port d'une règle est le **port de service de la transaction**, utilisé pour
l'aller et le retour ; les ports clients éphémères ne sont pas modélisés.
