"""Chamadas típicas de YouTube que o Rigel procura na transcrição.
Tudo é comparado sem acento e em minúsculas. Edite à vontade: um padrão por linha (regex simples).
"""

CHAMADAS = {
    "inscrição": [
        r"se inscrev\w*", r"inscreva[- ]?se", r"increva[- ]?se", r"inscrev\w+ no canal",
        r"suscri\w+", r"subscribe\w*",
    ],
    "like/sino": [
        r"deix\w+ (o |seu |aquele )?(like|joinha|gostei)", r"(da|de|dar) (um |o |aquele )?(like|joinha)",
        r"(ativ\w+|aciona\w*) (o |a )?(sininho|sino|notificac\w+)", r"campanita", r"dale (a )?like",
        r"hit the bell", r"smash (that|the) like",
    ],
    "comentários/compartilhar": [
        r"comenta(m)? (ai|aqui|embaixo|abaixo)", r"deix\w+ (seu|teu|um) comentario",
        r"compartilh\w+ (esse|este|o) video", r"comparte\w*",
    ],
    "descrição/links": [
        r"link (esta |ta |vai estar )?na descricao", r"(na|en la) descripcion", r"link (na|no) bio",
        r"clica (no|aqui no) (card|link)", r"(card|cartao) (aqui )?em cima",
    ],
    "patrocínio": [
        r"(esse|este) video (e |foi )?patrocinado", r"patrocinador\w*", r"(use|usa|utiliza) o cupom",
        r"cupom de desconto", r"codigo de desconto", r"(este|esse) video (es|e) patrocinado",
    ],
    "abertura/fechamento do canal": [
        r"(fala|ola|oi|e ai),? (galera|pessoal|turma)", r"bem[- ]vindos? (de volta )?ao (meu |nosso )?canal",
        r"bienvenidos? al canal", r"ate o proximo video", r"nos vemos no proximo video",
        r"hasta el proximo video", r"(um |uma )?(beijo|abraco) e ate", r"tchau,? (galera|pessoal)",
    ],
    "outros vídeos": [
        r"(no|en el) video anterior", r"(outro|otro) video (do|aqui do|del) canal",
        r"como (eu )?(mostrei|falei) (no|em outro) video", r"(confere|confira|assiste) (esse|este|o) video",
    ],
}
