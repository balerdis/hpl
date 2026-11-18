# Contrato de inclusion de artifacts HPL

Este documento fija la decision de distribucion de HPL. HPL se suma a una instalacion existente del CLI anfitrion — OpenCode o Claude Code, los dos adapters que el release registra (`ADAPTERS`, `src/hpl/adapters/__init__.py`): no instala ni reemplaza el cliente anfitrion, y no borra, mueve ni sobreescribe un artifact que no haya creado el. Lo que si pisa, y bajo que condicion, esta en la fila "Actualizacion o limpieza" de la tabla de abajo y en [Limitaciones aceptadas](arquitectura/arquitectura.md#limitaciones-aceptadas), que es donde vive el registro.

Toda implementacion y todo release futuro tienen que respetar este contrato. Si una necesidad no entra en estas reglas, se decide antes de distribuirla.

## Modelo aprobado

HPL se distribuye de forma aditiva. La instalacion reconoce lo que ya existe y agrega solamente lo que corresponde al release seleccionado.

| Tema | Decision |
| --- | --- |
| Cliente anfitrion | Un CLI soportado ya instalado: OpenCode o Claude Code. HPL no lo instala, actualiza, reemplaza ni desinstala. |
| Artifacts del usuario | Un artifact que el journal no reclama no se borra, mueve ni sobreescribe. Si ya existe uno en una direccion que la instalacion queria ocupar, se detecta, se informa como colision y se preserva: el paso devuelve `SKIP` y nunca escribe (`_file_step`, `src/hpl/core/planner.py`). |
| Propiedad | Se declara por artifact o modulo y por producto, no por directorio completo. Dos productos instalados bajo el mismo usuario nunca comparten la propiedad de un artifact: cada uno reclama y limpia solo lo suyo. |
| Actualizacion o limpieza | Solo se puede actualizar o remover un artifact que el journal reclama como propio de HPL. La huella no es permiso: dentro de ese conjunto se actualiza y se remueve **sin preguntar si el usuario lo edito despues**. `install` reescribe toda direccion reclamada cuyo contenido difiera del que se quiere colocar, y `uninstall` borra toda direccion reclamada, en los dos casos sin mirar de quien es el contenido actual (`_file_step` y `retire`, `src/hpl/core/planner.py`). Lo que protege una edicion a mano es el snapshot previo a escribir, no una negativa a escribir — ver [Limitaciones aceptadas](arquitectura/arquitectura.md#limitaciones-aceptadas). |
| Artifact existente | No pasa a ser de HPL por estar en una ruta conocida. Queda preservado. |

## Inclusion aprobada

Esta lista describe el release de HPL en si mismo: el binario `hpl` que este repositorio
construye y publica, con la identidad y el contenido que trae de fabrica. No describe ningun otro
binario basado en el mismo motor — una distribucion que construye su propio `identity.json` y su
propio contenido con `tools/build_zipapp.py` decide su propia lista de inclusion, y esta seccion no
se le aplica.

El release incluye solamente lo siguiente:

1. Todos los commands, el registro de skills y los assets del registro.
2. Los cinco servidores MCP que el contenido embarca (`src/hpl/content/mcp/`), cada uno con su forma de distribucion declarada en el descriptor: `cbm` y `engram` (`download`: binario de release con version y `sha256` fijos), `playwright` (`npm`: tarball del registry con `integrity` y su propio `package-lock.json`), y `context7` y `jira` (`remote`: un endpoint HTTPS, sin nada que descargar ni materializar). Ninguno se instala si no se lo nombra con `--mcp`.
3. Los siete plugins locales aprobados (`src/hpl/adapters/opencode/assets/plugins/`). Cinco se instalan con el prefijo del binario — `hpl` en esta distribución — y dos conservan su nombre de origen:
   - `engram.ts`, sin prefijo.
   - `zellij-status.js`, sin prefijo.
   - `zellij-state.ts` → `hpl-zellij-state.ts`, el estado de Zellij.
   - `skill-registry.ts` → `hpl-skill-registry.ts`, el plugin de registro (acompañado de `hpl-skill-registry.env`).
   - `apply-patch-scope.ts` → `hpl-apply-patch-scope.ts`, que agrega un párrafo a la descripción de `apply_patch` para que su imperativo de apertura no se lea como una prohibición del resto de las herramientas.
   - `orchestrator-notifier.ts` → `hpl-orchestrator-notifier.ts`, que avisa por `notify-send` cuando la sesión del orquestador queda `idle` o bloqueada esperando un permiso.
   - `secret-transport.ts` → `hpl-secret-transport.ts`, el transporte de credenciales: detecta un valor sensible por contexto o por el fallback explícito `<private>`, lo sustituye por una variable antes de que el mensaje se persista, la expone al ejecutar comandos y la redacta de la salida de una tool. Se instala sólo si el adapter declara al menos una operación de `credential_transport()` (ver `arquitectura.md`), acompañado de su propio sidecar de datos, `hpl-secret-transport-catalog.json` — el catálogo de detección, copiado sin cambios desde el content core.

   El notifier externo `@mohak34/opencode-notifier@0.2.4` se fija con su `package-lock.json` y se instala solo con `npm ci --ignore-scripts` durante la aceptación aislada.
4. Skills (`src/hpl/content/skills/`, veinticuatro en total; `_shared/` no cuenta -- no es una skill invocable, es la biblioteca de fragmentos que las demás cargan):
   - Core: `skill-creator`, `skill-improver`, `skill-registry`, `project-agents-bootstrap`, `cognitive-doc-design`.
   - SDD: `sdd-apply`, `sdd-archive`, `sdd-design`, `sdd-explore`, `sdd-init`, `sdd-onboard`, `sdd-propose`, `sdd-spec`, `sdd-tasks`, `sdd-verify`.
   - Contexto: `session-context`, `session-handoff`.
   - Git y colaboracion: `branch-pr`, `chained-pr`, `comment-writer`, `issue-creation`, `work-unit-commits`. Si alguna vez se agrega una skill a esta categoria, esta lista es la que se edita.
   - Quality, security y operations: `lazy-load-prompt-audit`.
   - Sin categoria fija: `api-service-contract-documentation`.

`tui.json`, toda configuración/salida de plugins TUI, `judgment-day` y la referencia de transporte de deployment de `lazy-load-prompt-audit` no se distribuyen. La ausencia de esa referencia bloquea el flujo de deployment con `blocked-missing-reference`; no se infiere ni se recrea. Si hay una copia local existente, se preserva y no se toca.

Los items no incluidos en esta lista no se distribuyen. No se agregan como efecto indirecto de otro modulo, ni se dejan referencias de configuracion hacia ellos.

## Contrato de MCP y dependencias

Antes de incorporar una dependencia o integracion MCP, HPL detecta si ya existe localmente.

| Situacion | Comportamiento obligatorio |
| --- | --- |
| Ya existe la dependencia o integracion | Se ofrece enlazarla. No se reemplaza ni se reinstala. |
| No existe | Se muestra fuente, version fija, integridad y accion a ejecutar. Luego se pide confirmacion del usuario para esa dependencia puntual. |
| Usuario rechaza | No se descarga, instala ni agrega una entrada de configuracion. Tampoco se deja una referencia huerfana. |
| Usuario confirma | Se obtiene e instala un artifact de release fijo, con la procedencia e integridad informadas. |

Cada release de HPL registra para cada dependencia su procedencia, version fija e integridad verificable. Nunca se usa `latest`, una version flotante ni una descarga sin identidad de release.

## Herramientas opcionales

Los plugins tienen que ser seguros cuando una herramienta opcional no esta instalada. En particular, el plugin de Zellij queda inerte si Zellij no existe: no falla la instalacion, no agrega una configuracion rota y no intenta instalar Zellij.

## Rollback y limpieza

El rollback limpia los artifacts que el journal reclama como creados por HPL, hayan sido modificados despues o no. La condicion es una sola —que el journal los reclame—, y no se puede probar esa propiedad sobre una direccion que no figura ahi: esa se preserva sin tocarla.

Un rollback no borra contenido del usuario que viva en una direccion que HPL no posee, incluso cuando comparta un archivo con un artifact HPL: dentro de un archivo de configuracion HPL posee claves, nunca el archivo, asi que el resto del documento sobrevive y un archivo que tuvo que crear puede quedar vacio. Un item agregado a una lista es la unica excepcion en el otro sentido: se lo localiza por huella, asi que uno que el usuario edito hasta volverlo irreconocible no se encuentra, se informa como `unaccounted` y se queda donde esta (`_retire_key`, `src/hpl/core/planner.py`). Los modulos o items que no forman parte de la inclusion aprobada tampoco se agregan ni se eliminan durante esta operacion.

## Limitaciones conocidas

Este documento no las repite: viven en un solo lugar, junto con su motivo. Una edicion a mano sobre un artifact de HPL no sobrevive al proximo `install` y `uninstall` la borra, los `append` quedan fuera del aviso `overwritten` por construccion y `uninstall` no tiene aviso equivalente — el porque de cada una y la recuperacion por snapshot, con su ventana de veinte generaciones, estan en [Limitaciones aceptadas](arquitectura/arquitectura.md#limitaciones-aceptadas). De las listas de "Inclusion aprobada", los servidores MCP, los plugins de OpenCode y las skills no se mantienen a mano sin control: `tests/test_inclusion_contract.py` deriva del arbol los servidores en `src/hpl/content/mcp/*.md`, los plugins en `src/hpl/adapters/opencode/assets/plugins/` y las skills en `src/hpl/content/skills/` (excepto `_shared/`, que no es una skill invocable), y los compara contra los nombres que esta seccion declara -- pero no de la misma forma para los tres. Para los plugins la comparacion es realmente bidireccional: un archivo de mas o de menos, en el arbol o en el documento, hace fallar el test, porque un nombre de plugin se reconoce por su extension (`.ts`/`.js`), no por pertenecer ya al arbol. Para los servidores MCP y las skills, un nombre solo cuenta como tal si coincide exactamente con un id o un nombre que el arbol ya tiene -- de otro modo la prosa libre de la seccion (`download`, `npm`, `remote` o una ruta) contaria como si fuera un artifact -- asi que el test solo prueba con certeza que el arbol no tenga mas de lo que el documento nombra. La direccion contraria para esos dos -- que el documento no nombre algo que el arbol ya no tiene -- la cierran las tres cifras tipeadas mas abajo ("cinco" servidores, "siete" plugins, "veinticuatro" skills), derivadas del mismo arbol: sacar un item sin tocar el documento hace que la cifra deje de coincidir. Lo que ni la comparacion de nombres ni la cifra detectan es que el documento nombre, ademas de todos los reales, un id o una skill que nunca existio: ese nombre se descarta antes de comparar, por el mismo filtro que evita que la prosa libre se cuente como artifact, y no cambia ninguna cifra. Por eso las skills se enumeran por nombre y no por categoria y excepcion, igual que los MCP y los plugins: una regla categorica ("todos los de contexto, excepto los que empiecen con un prefijo propio") no tiene una forma de comparacion contra el arbol que no reimplemente la categoria a mano en el test, que es la misma clase de mantenimiento manual sin control que esto busca cerrar. Ademas, el test verifica que a quien esta seccion describe "sin prefijo" o "con prefijo" coincida con `_RENAMED_ASSETS` (`src/hpl/adapters/opencode/adapter.py`). Lo que sigue sin verificacion automatica es que la salida realmente distribuida en un release coincida con lo que el arbol fuente contiene; eso sigue figurando en [Deudas sin unidad asignada](arquitectura/arquitectura.md#deudas-sin-unidad-asignada) con lo que hay que hacer en cada release hasta que exista.

## Control para releases

Antes de publicar, el release tiene que poder demostrar:

- La lista distribuida coincide con la inclusion aprobada.
- Cada artifact declara su propietario. La propiedad, y solo ella, habilita actualizarlo o removerlo.
- Los artifacts existentes del usuario se detectan y preservan.
- Cada MCP o dependencia nueva tiene confirmacion por dependencia, procedencia, version fija e integridad.
- Una negativa del usuario no deja descargas, instalaciones ni referencias de configuracion.
- La ausencia de Zellij mantiene inerte su plugin.
- `tui.json`, configuración/salida TUI, `judgment-day`, la referencia de transporte de deployment y todo item no incluido quedan fuera de la distribucion.
- El rollback no elimina contenido que HPL no posea.

De estos puntos, `tests/test_inclusion_contract.py` prueba que los plugins de OpenCode nombrados en la inclusion aprobada coincidan, en las dos direcciones, con lo que el arbol fuente contiene; que los servidores MCP y las skills que el arbol contiene esten todos nombrados alli, mas que las tres cifras tipeadas para servidores, plugins y skills coincidan con el conteo del arbol (lo que cierra, para esos dos, la direccion de que el documento no se haya quedado nombrando algo que el arbol ya no tiene); y que el prefijo declarado para cada plugin coincida con `_RENAMED_ASSETS`. Un id de servidor o una skill que el documento nombre de mas, sin haber existido nunca en el arbol, no lo detecta ninguno de esos dos mecanismos: se filtra antes de comparar, igual que la prosa libre de la seccion. Sigue demostrandose a mano, sin una prueba que lo derive, que la lista efectivamente distribuida en un release (el binario `hpl` publicado) coincida con la inclusion aprobada. Eso esta anotado como deuda en [Deudas sin unidad asignada](arquitectura/arquitectura.md#deudas-sin-unidad-asignada).
