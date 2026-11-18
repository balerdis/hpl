# Distribución de releases

HPL publica un solo archivo: `hpl`, un `zipapp` de la biblioteca estándar con shebang, construido
por `tools/build_zipapp.py` a partir de `src/hpl/`. Es el archivo entero que la persona instala —
el asset que [INSTALL.md](../INSTALL.md) e [INSTALL_BY_AGENT.md](../INSTALL_BY_AGENT.md) instruyen
descargar y verificar. No hay wheel, no hay venv, no hay shim aparte: HPL no declara ninguna
dependencia y lee su contenido desde adentro del propio zip, así que no queda nada más que empaquetar.
No hay pipeline de CI en este repositorio: los pasos siguientes son manuales, corridos por quien
prepara el release.

**`--identity` es obligatorio, sin excepción, incluso para el propio release de HPL.** El
motor puede construir un binario con una identidad distinta (nombre, wordmark, directorio de
datos y fuente de release propia — ver `docs/arquitectura/arquitectura.md`), `tools/build_zipapp.py`
exige el flag siempre: es la única forma de que "una distribución no puede olvidarse de dar su propia
identidad" sea literalmente cierto. El propio release de HPL pasa `src/hpl/identity.json`
explícitamente, igual que cualquier otra distribución pasaría el suyo.

**`install.sh` también se genera por identidad, con `tools/build_installer.py`.** El instalador
vive en la raíz del repositorio como una plantilla: un único bloque de identidad, delimitado por dos
líneas `# ====...====` cerca del principio del archivo, es el equivalente shell de `cli.py` — el
único lugar donde puede haber un literal de marca (`PRODUCT_ID`, `PRODUCT_DISPLAY_NAME`,
`PRODUCT_PROGRAM_NAME`, `PRODUCT_RELEASE_BASE_URL_DEFAULT`). `tools/build_installer.py --identity
<identity.json> --out <ruta>` reemplaza esas cuatro líneas por los valores del `identity.json` que
se le da, carácter por carácter idéntico en el resto del archivo, y valida el `identity.json` con
las mismas reglas de `core/identity.py` que usa `build_zipapp.py`. `--identity` y `--out` son
obligatorios igual que en `build_zipapp.py`, y `--out` se niega si ya existe. El release de HPL
corre este mismo comando con `src/hpl/identity.json`, igual que cualquier otra distribución.

Antes del paso 1, y sólo como información: `python3 tools/check_dependency_updates.py` lista, para cada
dependencia fijada en `src/hpl/content/mcp/*.md`, si existe una versión upstream más nueva
(`update-available`, `major-available`, `review-0.x`, `unversioned` o `error`). Es una herramienta de
mantenimiento que no se distribuye y no bloquea nada salvo que le pases `--strict`. Las versiones 0.x
siempre se revisan a mano, porque un minor 0.x puede romper. Subir una dependencia es cambiar `version` y
`checksum` en su descriptor de `content/mcp/*.md` (en playwright, además el lockfile y el `integrity`) y
publicar un release nuevo.

1. Sobre un commit con la suite verde (`PYTHONPATH=src:tests python3 -m unittest discover -s tests -q`), confirmá que `pyproject.toml` declara la versión que vas a publicar y creá el tag anotado `vX.Y.Z` sobre ese commit.
2. Construí el artefacto:

   ```sh
   python3 tools/build_zipapp.py --identity src/hpl/identity.json --out dist/hpl
   ```

   `--identity` se valida contra las reglas de `src/hpl/core/identity.py` antes de escribir nada
   — nombre con sólo letras y números (sin acentos, sin guiones), no más ancho de lo que entra en la
   grilla del wordmark, URLs de release `https` con host real — y `--source` tiene que ser el propio
   directorio del paquete (`.../hpl`, con `core/content.py` adentro), no el directorio que lo
   contiene: pasar el de arriba arma un archivo anidado `hpl/hpl/` que se rechaza en el
   momento de construir, con el error nombrando el motivo, en vez de fallar recién al ejecutar el
   binario con un `ModuleNotFoundError`. Deja `dist/hpl` (ejecutable, con shebang) y
   `dist/hpl.sha256` al lado.
3. Generá la evidencia del release con `tools/build_release_evidence.py`, apuntando al tag:

   ```sh
   python3 tools/build_release_evidence.py \
     --artifact dist/hpl \
     --tag vX.Y.Z \
     --output dist/release-manifest.json
   ```

   El script no construye el artefacto — lo toma tal cual existe, lo corre (`hpl doctor --json`)
   para confirmar que el `hpl_version` que reporta coincide con `pyproject.toml` en ese commit, y
   sólo entonces certifica el commit y el hash (`release-manifest.json` y un `.sha256`). Sin `--tag`,
   describe el `HEAD` limpio; con el worktree sucio, se niega. `assets` en el manifest nombra
   cuatro archivos: además de `hpl`, certifica `install.sh`, `tools/build_zipapp.py` y
   `tools/build_installer.py` leyendo los bytes exactos de cada uno del commit con
   `git show <commit>:<ruta>` (no del working tree) y comparándolos contra la copia del working
   tree — los archivos que este mismo paso 4 sube. `build_zipapp.py` y `build_installer.py` se
   publican con su propio nombre plano (sin el prefijo `tools/`, porque los assets de un release de
   GitHub no tienen subcarpetas) y su propio `.sha256` al lado, igual que `hpl`: una
   distribución que descarga el release no tiene que clonar el repositorio entero sólo para
   conseguir los scripts que construyen su propio binario y su propio instalador. El script se
   niega si el commit no tiene alguno de los cuatro archivos, o si el del working tree no coincide
   con el del commit; en cualquiera de esos casos, subir igual dejaría un release sin un asset que
   otro paso necesita, o con una copia distinta de la que el manifest certificó.
4. Publicá en GitHub Releases, sobre ese mismo tag, estos ocho archivos -- `release-manifest.json`
   mismo, los cuatro que certifica su lista `assets`, y el `.sha256` de cada uno de los tres que lo
   necesita, tal como los escribe el paso anterior:
   `hpl`, su `.sha256`, `release-manifest.json`, `install.sh` (el archivo en la raíz del
   repositorio, tal cual está en ese commit — no se genera en este paso, se sube directo, y es el
   mismo cuyo hash quedó certificado en el paso anterior; es, además, exactamente lo que
   `tools/build_installer.py --identity src/hpl/identity.json` reproduciría, así que el propio
   release de HPL no necesita correr ese comando para publicar el suyo), `build_zipapp.py` con
   su propio `.sha256` (el archivo en `tools/build_zipapp.py`, subido con el nombre plano que el
   manifest certificó), y `build_installer.py` con su propio `.sha256` (el archivo en
   `tools/build_installer.py`, subido con el nombre plano que el manifest certificó). `install.sh`,
   `build_zipapp.py` y `build_installer.py` tienen que publicarse en este mismo release, y no en
   ningún otro lugar (por ejemplo, servido crudo desde `raw.githubusercontent.com`): todo lo que
   instala vive detrás de `releases/latest/download/`, así que si alguno de los scripts viviera en
   una URL aparte podría quedar apuntando a un binario de un release distinto del que lo acompaña —
   exactamente el tipo de desincronización que este esquema existe para evitar, y la razón por la
   que el paso 3 ya lo certifica antes de que llegues a subir nada. El checksum de `hpl`
   registra sólo el basename, nunca una ruta de staging, para que `sha256sum -c` funcione tal como
   se descargó.
5. El release de GitHub debe ser no-draft y no-prerelease para que el contrato `latest` lo ofrezca.
   Corré `tools/verify_release_assets.py` contra el manifest y el tag para confirmar que lo publicado
   coincide con lo certificado, en vez de chequearlo a mano:

   ```sh
   python3 tools/verify_release_assets.py \
     --manifest dist/release-manifest.json \
     --tag vX.Y.Z
   ```

   Descarga cada asset del manifest por su ruta versionada (`releases/download/vX.Y.Z/<asset>`) y
   compara su SHA-256 contra el manifest; si además `vX.Y.Z` resulta ser el release `latest`, repite
   la comparación contra `releases/latest/download/<asset>` — la ruta que `README.md` e
   `INSTALL.md` realmente publicitan, y una afirmación distinta de la ruta versionada. Si el tag
   todavía no es el `latest` (por ejemplo, publicaste un release más nuevo mientras tanto), el script
   lo reporta y salta ese chequeo en vez de fallar por una razón que no es un defecto de este release.
   Imprime una línea por asset y termina con código de salida distinto de cero si algo no coincide.

## Actualizar desde un build local

El repositorio público `balerdis/hpl` publica las releases, y `hpl upgrade` las lee de ahí (`latest_release_api_url`, `asset_url_template` e `install_base_url_default` de `identity.json`). Si esas URLs no se pueden alcanzar —sin red, GitHub limita las consultas anónimas o una copia propia apunta a un repositorio que no es público—, `hpl upgrade` termina con un mensaje claro («the release repository answered HTTP 404 ... it may be private or unreachable») y código 1, y el aviso de versión nuevo del menú queda en silencio.

Una instalación también se puede actualizar desde un build local, con el árbol del repositorio en la versión que querés instalar:

```sh
python3 tools/build_zipapp.py --identity src/hpl/identity.json --out <dir>/hpl
cp <dir>/hpl ~/.local/bin/hpl
hpl update --cli <cli>
```

El primer paso arma el zipapp; el segundo lo copia sobre el binario instalado (con `cp` sobre el archivo, no con `upgrade`); el tercero reaplica en la CLI elegida (`opencode` o `claude-code`) la selección que esa instalación ya tiene registrada. `hpl -V` confirma la versión del binario nuevo.

## Antes de empezar: la suite y una revisión que quiera romperlo

Este proyecto no tiene CI, y es una decisión —no un olvido— registrada en
[Deudas sin unidad asignada](arquitectura/arquitectura.md#deudas-sin-unidad-asignada). Lo que ocupa su
lugar son dos pasos, y sólo el primero suele recordarse.

**Uno: la suite completa, sobre un árbol quieto.** `PYTHONPATH=src:tests python3 -m unittest discover -s
tests -q`, redirigida a un archivo y leyendo el código de salida, nunca la cola de un pipeline. Sobre un
árbol quieto quiere decir sin ninguna mutación de prueba adentro: una suite verde sólo describe el árbol
que existía cuando corrió, y un agente detenido puede haber escrito después.

**Dos: una revisión adversarial en contexto fresco, cuya única consigna es romper lo que se acaba de
escribir.** No una lectura del diff buscando errores: alguien que construya el escenario que debería
hacer fallar cada control nuevo y lo **corra**. Si un área resiste, que diga qué intentó; un «se ve bien»
sin intento de ruptura no cuenta como revisión.

El segundo paso existe porque el primero no puede hacer ese trabajo, y conviene entender por qué antes de
saltearlo. La suite prueba que no se rompió lo que ya funcionaba. No puede probar que lo nuevo haga lo que
dice, porque el test que lo afirma lo escribe quien escribió el código, con la misma idea en la cabeza: si
el control mira la variable equivocada, el test que lo acompaña mira la misma.

Los defectos más caros los encuentra la revisión, no la suite, que puede estar verde en todos estos
casos: un guardián de cobertura que acepta un `print("x.py")` como prueba de que un script se ejecuta;
una lista de exenciones que compara por nombre de archivo, así que cualquier archivo nuevo llamado igual
queda exento; tests que sólo corren si ya existe un build previo y que en un clon limpio pueden salir a la
red; y una bandera `--offline` que descarga igual cuando la caché está vacía.

Tres de esos cuatro son la misma forma de defecto: **un control que aprueba mirando un proxy en vez del
hecho**. Es la forma que más cuesta ver desde adentro, porque el proxy se eligió justamente por ser más
fácil de medir.
