# Signature et provenance (CDC §15)

Deux mécanismes, deux questions différentes. Les confondre coûte soit de
l'argent pour rien, soit une Phase 6 qui ne passe pas ses critères.

| | Question posée | Qui répond | Coût | État |
|---|---|---|---|---|
| **Provenance Sigstore** | *Ce fichier vient-il bien de ce dépôt, de ce commit ?* | GitHub / Fulcio / Rekor | 0 € | ✅ en place |
| **Authenticode** | *Windows doit-il laisser l'utilisateur ouvrir ce fichier ?* | Une AC du magasin Windows | ~10 $/mois | ⬜ à souscrire |

---

## Ce que Sigstore fait — et ne fait pas

Le workflow de release produit une **attestation de provenance SLSA** signée par
Sigstore : `actions/attest-build-provenance` échange le jeton OIDC du job contre
un certificat éphémère Fulcio, signe l'empreinte de l'installateur, et consigne
l'opération dans le journal public Rekor.

N'importe qui peut alors vérifier :

```bash
gh attestation verify Desky-0.11.0-setup.exe --repo HyroHyKen/Desky
```

La commande répond : *cette empreinte exacte a été produite par ce dépôt, par ce
workflow, depuis ce commit*. C'est une garantie forte et réelle contre un binaire
réempaqueté ou un miroir hostile, et elle ne coûte rien.

**Elle ne remplace pas Authenticode.** La racine Fulcio n'est pas dans le
*Microsoft Trusted Root Program* : pour Windows, un `.exe` signé uniquement par
Sigstore reste un fichier d'éditeur inconnu. Les propriétés du fichier
n'afficheront aucun onglet « Signatures numériques », et SmartScreen se
comportera exactement comme aujourd'hui. `cosign sign-blob` ne change rien à ce
constat : le format produit est une signature détachée, pas une signature
incorporée au PE, et c'est le magasin de confiance qui bloque, pas le format.

Conséquence concrète : le critère d'acceptation de la Phase 6 — « aucun
avertissement SmartScreen » — **n'est pas atteint par Sigstore seul**.

---

## Authenticode : l'option retenue

### Azure Artifact Signing (ex-Trusted Signing)

C'est bien l'option que le §15 désignait, sous son ancien nom.

- **~9,99 $/mois**, contre 150 à 300 $/an pour un certificat OV classique.
- **Pas de token USB** : la signature s'appelle depuis la CI, ce qui est la
  raison principale de la préférer ici — un HSM physique et un runner GitHub ne
  vont pas ensemble.
- **Éligibilité géographique**, et c'est le point à vérifier avant de payer :
  ouvert aux **organisations** des USA, du Canada, de l'**Union européenne** et
  du Royaume-Uni ; ouvert aux **particuliers** en USA et Canada **seulement**.

  Une entité française passe donc par la voie *organisation*, pas *individu*.
  Il faut une personne morale et une validation d'identité par Microsoft
  (quelques jours ouvrés).

### Ce qu'il faut poser dans les secrets du dépôt

Une fois le compte et le profil de certificat créés, six secrets — le workflow
saute silencieusement la signature tant qu'ils sont absents, et le signale dans
les notes de version :

| Secret | Exemple |
|---|---|
| `SIGNING_ENDPOINT` | `https://weu.codesigning.azure.net/` |
| `SIGNING_ACCOUNT` | nom du compte Artifact Signing |
| `SIGNING_PROFILE` | nom du profil de certificat |
| `AZURE_TENANT_ID` | GUID du tenant |
| `AZURE_CLIENT_ID` | GUID de l'app registration |
| `AZURE_CLIENT_SECRET` | secret de l'app registration |

L'*endpoint* doit correspondre à la région du compte : `weu` pour l'Europe de
l'Ouest.

> Le secret client est un pis-aller pratique. À terme, préférer la fédération
> OIDC (`azure/login` + *workload identity*) : plus rien à faire tourner, et
> aucun secret de longue durée dans le dépôt.

### Ce que la signature ne donne pas non plus

**La réputation SmartScreen se construit, elle ne s'achète plus.** Un binaire
fraîchement signé reste inconnu au début et déclenche encore un avertissement —
plus doux que pour un binaire non signé, mais présent. La réputation s'accumule
sur l'**identité du signataire** au fil des téléchargements : signer chaque
version avec le même profil fait hériter les suivantes de la confiance acquise.

Le certificat **EV** ne change plus rien sur ce point : son contournement
immédiat de SmartScreen a été retiré en 2024. Payer 400 $/an pour un EV dans le
seul but d'éviter l'avertissement n'a plus de justification.

### Si la voie Azure se ferme

- **SignPath Foundation** — signature OV gratuite pour les projets open source
  qualifiés. À regarder en premier si Desky est publié sous licence libre.
- **Certificat OV** chez DigiCert, Sectigo ou GlobalSign, 150 à 300 $/an. Depuis
  juin 2023 la clé privée doit vivre dans un HSM ou sur un token matériel, ce qui
  complique nettement la signature depuis la CI.

---

## Résumé de la position actuelle

La chaîne livre aujourd'hui un installateur **attesté mais non signé**. C'est un
état assumé et temporaire :

1. La provenance Sigstore est déjà branchée et ne demande aucune démarche. Elle
   couvre le risque « ce n'est pas le vrai binaire ».
2. Authenticode reste à souscrire. Il couvre le risque « l'utilisateur abandonne
   devant l'avertissement », que le §15 juge rédhibitoire — et il est le seul à
   le couvrir.

Le workflow est écrit pour que l'étape 2 soit un simple ajout de secrets :
aucune ligne de YAML à modifier le jour où le compte existe.

## Sources

- [Code signing options for Windows app developers — Microsoft Learn](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options)
- [SmartScreen reputation for Windows app developers — Microsoft Learn](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)
- [Artifact attestations — GitHub Docs](https://docs.github.com/en/actions/concepts/security/artifact-attestations)
- [actions/attest-build-provenance](https://github.com/actions/attest-build-provenance)
- [Azure/artifact-signing-action](https://github.com/Azure/artifact-signing-action)
- [cosign — « Can cosign replace SignTool.exe for Windows Binaries? »](https://github.com/sigstore/cosign/issues/1443)
- [Using ModernGL in CI](https://moderngl.readthedocs.io/en/stable/install/using-moderngl-in-ci.html)
