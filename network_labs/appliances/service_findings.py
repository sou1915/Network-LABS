"""Explain observed service probes without inferring a network root cause."""


def findings(report):
    rows = []
    def add(code, status, message, next_step, evidence):
        rows.append(dict(code=code, status=status, message=message, next_step=next_step, evidence=evidence))
    endpoint = report['endpoint']
    if endpoint['status'] != 'ready':
        add('SOURCE_NOT_READY', endpoint['status'],
            'La source ne présente pas un conteneur actif, un lien opérationnel et une IPv4 unique observables.',
            'Consulter inspect pour ce node : état du conteneur, interface eth0 et adresse IPv4/DHCP.', endpoint)
    for stage in report['stages']:
        kind, status = stage['stage'], stage['status']
        if status in ('unknown', 'blocked'):
            add(kind.upper() + '_INCOMPLETE', status,
                'Le résultat de cette étape est indisponible, non pris en charge ou ambigu ; aucun succès ne peut être affirmé.',
                'Consulter les détails JSON et les limites du profil avant de modifier la configuration.', stage)
        elif kind == 'dns':
            if status == 'passed':
                add('DNS_A_RECEIVED', status, 'Le serveur DNS interrogé a répondu avec une ou plusieurs adresses IPv4 pour ce nom.',
                    'Une réponse DNS ne prouve pas que le service à cette adresse est joignable.', stage)
            elif stage.get('rcode') == 3:
                add('DNS_NXDOMAIN', status, 'Le serveur DNS interrogé indique que ce nom n’existe pas (NXDOMAIN).',
                    'Vérifier le nom saisi, la zone et les enregistrements sur ce serveur DNS.', stage)
            elif stage.get('rcode') == 0:
                add('DNS_NO_DIRECT_A', status, 'La réponse DNS ne contient pas d’adresse A directement associée au nom demandé.',
                    'Vérifier les enregistrements A. Cette sonde ne suit pas les chaînes CNAME.', stage)
            elif stage.get('rcode') is not None:
                add('DNS_ERROR_RESPONSE', status, 'Le serveur DNS a renvoyé un code d’erreur.',
                    'Consulter le rcode dans les preuves et les journaux du serveur DNS.', stage)
            else:
                add('DNS_NO_ANSWER', status, 'La sonde n’a pas obtenu de réponse DNS exploitable dans son délai.',
                    'Vérifier le résolveur du node, le service DNS, UDP/53, les routes et le chemin retour ; la cause n’est pas déterminée.', stage)
        elif kind == 'sntp':
            if status == 'passed':
                add('SNTP_REPLY_RECEIVED', status, 'Une réponse SNTP valide a été reçue ; le décalage estimé est disponible en JSON.',
                    'Un seul échange non authentifié ne synchronise aucune horloge et ne garantit ni précision ni identité du serveur.', stage)
            else:
                add('SNTP_NO_ANSWER', status, 'La sonde SNTP n’a pas obtenu de réponse exploitable dans son délai.',
                    'Vérifier UDP/123, les routes et le serveur ; cet échec ne détermine pas sa cause.', stage)
        elif kind == 'tcp':
            if status == 'passed':
                add('TCP_CONNECTED', status, 'Une connexion TCP a été établie vers l’adresse et le port demandés.',
                    'Cela valide cette connexion, pas le comportement de l’application.', stage)
            elif stage.get('error') == 'ConnectionRefusedError':
                add('TCP_REFUSED', status, 'La tentative de connexion TCP a reçu un refus.',
                    'Vérifier le port, le processus à l’écoute et les règles de rejet. Un refus ne prouve pas à lui seul que le service est arrêté.', stage)
            else:
                add('TCP_NOT_CONNECTED', status, 'La connexion TCP n’a pas été établie par cette sonde.',
                    'Vérifier les routes aller/retour, le filtrage et le service à l’écoute ; ne pas déduire la cause du seul échec.', stage)
        elif kind == 'https' and stage.get('error') == 'CERTIFICATE_VERIFY_FAILED':
            add('HTTPS_CERTIFICATE_REJECTED', status, 'La vérification du certificat TLS a échoué.',
                'Vérifier la CA fournie, le nom/IP du certificat et sa validité. Aucun contournement du contrôle TLS.', stage)
        elif kind in ('http', 'https'):
            if kind == 'https' and stage.get('certificate_verified') is True:
                add('HTTPS_TLS_VERIFIED', 'passed', 'Le certificat a été validé avec la CA fournie et le nom/IP demandé.',
                    'Cette validation ne vérifie pas la révocation ni le contenu de la page.', stage)
            code = stage.get('http_status')
            if code is not None:
                message = ('Le serveur a répondu à HEAD avec un statut HTTP 2xx.' if status == 'passed'
                           else f'Le serveur a répondu à HEAD avec le statut HTTP {code}, hors critère 2xx.')
                next_step = ('Le contenu de la page n’a pas été téléchargé ni validé.' if status == 'passed'
                             else 'Vérifier le chemin, les droits et les journaux HTTP. Les redirections ne sont pas suivies ; HEAD peut être refusé même si GET fonctionne.')
                add('HTTP_STATUS_RECEIVED', status, message, next_step, stage)
            else:
                add('HTTP_NO_STATUS', status, 'La sonde HTTP n’a pas obtenu de statut HTTP exploitable.',
                    'Vérifier le service HTTP et son délai de réponse. La connexion TCP précédente était distincte de cette tentative HTTP.', stage)
    return rows
