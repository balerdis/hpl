# HPL: núcleo agnóstico y adapters por CLI

HPL separa **qué distribuye** (contenido común a cualquier CLI de agentes) de **cómo lo materializa** (un adapter por CLI). El motor no conoce nombres de CLIs: recibe contenido del núcleo, se lo da al adapter, y el adapter decide dónde va y con qué forma.

Este documento describe la arquitectura de HPL 7.7.8: el diseño vigente y las limitaciones que se aceptan. Cuando una parte deja de ser cierta se corrige o se anota como deuda; nunca se deja parada.

---

## Decisiones tomadas

| Tema | Decisión |
|------|----------|
| Estilo arquitectónico | Hexagonal (puertos y adaptadores). No Clean Architecture. |
| CLIs soportados | OpenCode y Claude Code. La arquitectura admite N sin tocar el núcleo. |
| Catálogo de artefactos | Generado, no escrito a mano. |
| Agentes SDD | Los 10 de la línea SDD son subagentes reales, cada uno con su prompt y su modelo configurable. |
| Interfaz de usuario | TUI por defecto + flags equivalentes para modo desatendido. |
| Lenguaje y dependencias | Python 3.12+, sin ninguna dependencia. El frontmatter de los descriptores se parsea con un lector propio y estricto, que rechaza lo que no entiende en vez de interpretarlo a medias. |
| Punto de entrada | Un solo archivo ejecutable (`zipapp` con shebang y bit ejecutable), instalado en `~/.local/bin/hpl`. Sin venv privado. |

### Las dos reglas que gobiernan el diseño

> **1. Ningún módulo fuera de `adapters/` puede mencionar el nombre de un CLI.**

Si aparece un `if cli_id == "opencode"` en `core/`, `tui/` o `infra/`, es un defecto de arquitectura, no un detalle de implementación. Un test lo verifica automáticamente.

> **2. El núcleo guarda la intención; el adapter guarda el deletreo.**

El núcleo declara *qué se quiere que pase*. El adapter sabe *cómo se escribe eso en un CLI concreto*. Un campo que sirve para un solo CLI no pertenece al descriptor.

La prueba para saber de qué lado va un campo: **¿tendría sentido en un CLI que todavía no soportamos?** Si la respuesta es no, es deletreo y va al adapter.

---

## Qué problema resuelve

Un producto que se instala en varios CLIs de agentes corre un riesgo: que la adaptación a cada uno quede repartida entre el catálogo, el motor y los archivos de configuración, sin un lugar identificable. Entonces agregar un CLI obliga a modificar el motor, el catálogo y el validador.

HPL fija un lugar: cada CLI vive en su propio directorio bajo `adapters/` y se registra. Agregar un CLI significa escribir ese directorio nuevo; el motor, el catálogo y el contenido no cambian.

---

## Arquitectura

```
        PUERTOS DRIVER                                     PUERTOS DRIVEN
        (quién nos usa)                                    (a quién usamos)

   ┌──────────────┐                                    ┌──────────────────┐
   │     TUI      │──┐                            ┌───►│   CliAdapter     │
   └──────────────┘  │                            │    │  opencode        │
   ┌──────────────┐  │   ┌────────────────────┐   │    │  claudecode      │
   │  CLI (flags) │──┼──►│      NÚCLEO        │───┤    └──────────────────┘
   └──────────────┘  │   │                    │   │    ┌──────────────────┐
   ┌──────────────┐  │   │  contenido         │   ├───►│   FileSystem     │
   │ Agente (JSON)│──┘   │  planner           │   │    │  PosixFileSystem │
   └──────────────┘      │  journal           │   │    └──────────────────┘
                         │  registry          │   │    ┌──────────────────┐
                         └────────────────────┘   ├───►│ JournalStore     │
                                                  │    │ SnapshotStore    │
                                                  │    │ ModelAssignment- │
                                                  │    │ Store (archivos) │
                                                  │    └──────────────────┘
                                                  │    ┌──────────────────┐
                                                  └───►│ Downloader (HTTP)│
                                                       │ NpmInstaller     │
                                                       │ MCPProcess       │
                                                       │ (subprocess)     │
                                                       └──────────────────┘
```

El núcleo no importa nada de `adapters/` ni de `infra/`. Recibe implementaciones por constructor. Los puertos son los de `src/hpl/ports/` y sus implementaciones las de `src/hpl/infra/`; sólo hay filesystem POSIX, porque Windows no está soportado.

---

## El núcleo de contenido

Todo el contenido tiene una sola forma: **un archivo markdown con frontmatter**. El frontmatter es el descriptor, y lo que sigue es el cuerpo. Un único formato para todas las categorías, y por lo tanto un único parser.

| Categoría | Contiene | Qué es agnóstico |
|-----------|----------|------------------|
| `skills/` | `SKILL.md` + `references/` | Todo |
| `agents/` | Rol, modo, herramientas, delegación permitida, y el prompt como cuerpo | Todo el cuerpo; el formato de declaración no |
| `commands/` | Descripción, rol que lo ejecuta, contexto de ejecución | Todo el cuerpo; el frontmatter no |
| `system-prompt/` | La instrucción global que el CLI carga en cada sesión | Todo el cuerpo; el nombre y la ubicación del archivo no |
| `mcp/` | Servidores MCP: id, versión fija, integridad, argv de instalación y runtime, probe | Todo |
| `policies/` | TDD estricto, ChainPR, gates de fase, backend de artefactos | Todo |

`system-prompt/` es una categoría propia y no una política: es un artefacto único con su propio render. OpenCode lo instala como `AGENTS.md` en la raíz de su configuración; otro CLI puede darle otro nombre, otra ubicación, o cargarlo desde su archivo de settings.

**No hay una categoría `prompts/`.** El prompt de un agente es el cuerpo del archivo del agente. Que ese prompt viaje después en un archivo separado o embebido en la declaración del agente es una decisión del CLI, no del contenido, y por eso existe la capacidad `prompts`: OpenCode la declara y recibe dos artefactos, un CLI que embebe el prompt la niega y recibe uno solo.

### Ejemplo de descriptor

```markdown
---
name: sdd-verify
description: Sole readiness authority for executable and configuration changes
mode: subagent
requires_tools: [read, write, bash]
optional_tools: [codebase-memory]
model_configurable: true
---

# SDD Verify

You are HPL's sole readiness authority for executable and configuration changes.
...
```

Ese descriptor no dice nada sobre OpenCode. El adapter de OpenCode lo convierte en una entrada bajo `agent` de `opencode.json` más un archivo de prompt; un adapter de Claude Code lo convertiría en un `.claude/agents/sdd-verify.md` con frontmatter y el prompt embebido. Ninguno de los dos requiere tocar el descriptor.

### Estado del contenido

| Categoría | Presente |
|-----------|---------:|
| `skills/` | 24, más `_shared/` |
| `commands/` | 16 |
| `agents/` | 16 |
| `system-prompt/` | 1 |
| `mcp/` | 5 |

### Campos agnósticos del frontmatter

El frontmatter de un descriptor expresa intención, no el deletreo de un CLI. Cada campo agnóstico reemplaza uno que sería de OpenCode:

| Deletreo de OpenCode | Qué es en realidad | Campo agnóstico |
|----------------|---------------------|-----------------|
| `subtask: true` | Contexto de ejecución | `execution: isolated \| inline` |
| `agent: hpl-orchestrator` | Agente propio de HPL | `runs_as: orchestrator` |
| `agent: plan` / `agent: build` | Agentes nativos de OpenCode | `runs_as: planner \| builder` |
| `agent:` ausente | El agente por defecto del CLI | `runs_as: default` |
| `permission.task` | A qué agentes puede delegar | `may_delegate_to: [...]` |

El adapter de OpenCode mapea `orchestrator` a `hpl-orchestrator`, `planner` a su agente nativo `plan`, `isolated` a `subtask: true`, y `may_delegate_to` a su bloque `permission`. Otro CLI usa sus propios nombres sin que el descriptor cambie.

### El pipeline de materialización

```
1. RESOLVE      el núcleo arma el conjunto de contenido a instalar
2. ADAPT        el adapter mapea categoría → ruta concreta de ese CLI
3. DECORATE     el adapter envuelve: frontmatter, claves JSON, formato de config
4. MATERIALIZE  el motor escribe, con journal de ownership y rollback
```

Los pasos 1 y 4 son núcleo puro y no conocen ningún CLI. Los pasos 2 y 3 son exclusivos del adapter. El motor nunca inspecciona el contenido de lo que escribe.

---

## Puertos

### `CliAdapter` — el puerto principal

Separa **dónde** (rutas) de **cómo** (render). Esa separación es la que evita que el motor tenga que preguntar de qué CLI se trata.

```python
class CliAdapter(Protocol):
    # --- Identidad ---
    @property
    def id(self) -> str: ...
    @property
    def display_name(self) -> str: ...
    def tier(self) -> SupportTier: ...          # FULL | PARTIAL | EXPERIMENTAL
    def capabilities(self) -> CapabilityManifest: ...

    # --- Detección ---
    def detect(self, env: Environment) -> Detection: ...

    # --- Dónde: layout de rutas ---
    def layout(self, env: Environment) -> Layout: ...

    # --- Cómo: render de cada categoría. Cada uno recibe el layout ya
    # resuelto, así el adapter no guarda estado propio de una máquina. ---
    def render_skill(self, layout: Layout, skill: Skill) -> list[Artifact]: ...
    def render_agent(self, layout: Layout, agent: AgentDescriptor) -> list[Artifact]: ...
    def render_command(self, layout: Layout, command: CommandDescriptor) -> list[Artifact]: ...
    def render_prompt(self, layout: Layout, prompt: PromptDescriptor) -> list[Artifact]: ...
    def render_mcp(self, layout: Layout, server: McpServer, resolved: Resolved) -> list[Artifact]: ...
    def render_policy(self, layout: Layout, policy: PolicyDescriptor) -> list[Artifact]: ...

    # --- Lo que el adapter aporta por su cuenta ---
    def own_artifacts(self, layout: Layout) -> list[Artifact]: ...

    # --- Modelos: solo si capabilities().per_agent_model es True ---
    def model_catalog(self, env: Environment) -> ModelCatalog: ...
    def read_model_assignments(self, env: Environment) -> dict[str, ModelAssignment]: ...
```

### `Layout` — las anclas de ruta

```python
@dataclass(frozen=True)
class Layout:
    config_dir: Path            # raíz de configuración del CLI
    settings_file: Path | None  # archivo de config principal, si existe
    skills_dir: Path | None
    agents_dir: Path | None
    commands_dir: Path | None
    prompts_dir: Path | None  # None si el CLI embebe el prompt en el agente
    plugins_dir: Path | None
    system_prompt_file: Path | None
```

Un `None` significa "este CLI no tiene ese concepto" y debe ser coherente con el manifiesto de capacidades. El registry lo verifica al registrar.

### `Artifact` — la unidad que el motor sabe escribir

El motor conoce exactamente dos formas de artefacto. Nada más. El adapter las entrega ya terminadas: el motor nunca abre `content` ni interpreta `value`.

```python
@dataclass(frozen=True)
class FileArtifact:
    id: str
    path: Path                  # ruta absoluta, ya resuelta por el adapter
    content: bytes              # contenido final, ya decorado
    mode: int = 0o644

@dataclass(frozen=True)
class ConfigKeyArtifact:
    id: str
    path: Path                  # archivo de configuración
    pointer: str                # dirección RFC 6901, ej. "/agent/sdd-apply/model"
    value: object
    codec: Codec = Codec.JSON   # cómo se parsea y serializa ese archivo

Artifact = FileArtifact | ConfigKeyArtifact
```

Direccionar por puntero en lugar de por clave plana es lo que permite escribir `/agent/sdd-apply/model` sin que el motor entienda el esquema del CLI.

#### Las cuatro operaciones del motor

Es todo lo que el motor sabe hacer con un artefacto. Cada operación tiene exactamente dos implementaciones, y agregar un CLI no agrega ninguna.

| Operación | `FileArtifact` | `ConfigKeyArtifact` |
|-----------|----------------|---------------------|
| Detectar colisión | ¿El path ya existe? | ¿El puntero ya resuelve a algo? |
| Escribir | Escritura atómica de `content` | `set_at(doc, pointer, value)` y reescritura atómica |
| Hashear | `sha256(content)` | `sha256` de la serialización canónica de `value` |
| Revertir | Borrar el archivo | `unset_at(doc, pointer)` |

`set_at` y `unset_at` son dos funciones genéricas que navegan un árbol de diccionarios y listas creando lo que falte. No mencionan ningún CLI.

#### La excepción: punteros que agregan a una lista

Un puntero terminado en `/-` no direcciona un casillero sino el final de una lista. Hoy tres artefactos lo usan: `/instructions/-`, `/plugin/-` y `/skills/paths/-`. Eso rompe dos de las cuatro operaciones, y las dos se arreglan con la huella:

| Operación | Por qué no sirve lo normal | Cómo se resuelve |
|-----------|---------------------------|------------------|
| Detectar colisión | En `/-` nunca resuelve nada, así que jamás habría colisión y reinstalar duplicaría la entrada | Hay colisión si algún ítem de la lista tiene la huella del valor que íbamos a agregar |
| Revertir | Guardar el índice no sirve: el usuario puede reordenar la lista y el índice pasaría a apuntar a algo suyo | Se busca el ítem cuya huella coincide con `after_digest` y se quita ese |

Por eso el ítem se identifica por **lo que es** y no por **dónde está**.

Eso tiene una consecuencia que hay que decir en voz alta: **un ítem de lista no tiene dirección propia que inspeccionar, y esa falta de dirección es la que le impide a un append comportarse como el resto del desinstalador.** Si la lista todavía tiene ítems y ninguno lleva la huella registrada, hay dos causas posibles y son indistinguibles:

- el usuario borró nuestro ítem, o
- el usuario lo editó en el lugar, y ahora es idéntico a un ítem que hubiera puesto él.

No hay dato en el journal que las separe. Ninguna de las dos es una remoción, así que el desinstalador las reporta como un segundo resultado: **`unaccounted`**. `removed` es una afirmación sobre algo que HPL hizo, y acá no sería cierta.

**La ambigüedad necesita sobrevivientes**, y afirmarla donde no existe sería su propia imprecisión. Los cuatro estados posibles:

| Estado al desinstalar | ¿Ambiguo? | Resultado |
|-----------------------|-----------|-----------|
| El archivo de configuración no existe | No: se fue con el archivo | `removed` |
| El archivo existe pero la lista no | No: se fue con la lista | `removed` |
| La lista existe y está vacía | No: no queda nada que pueda ser una versión cambiada del nuestro | `removed` |
| La lista tiene ítems y ninguno es el nuestro | **Sí** | `unaccounted` |

Además, dos artefactos no pueden agregar **el mismo valor** al mismo puntero: la lista no podría distinguirlos y nada aguas abajo podría decir cuál de los dos tiene. Agregar valores distintos sí es legítimo y por eso los appends quedan exentos de la regla general de direcciones únicas.

#### Códecs de configuración

El puntero navega cualquier árbol, pero parsear y serializar el archivo depende de su formato. El adapter lo declara y el motor delega:

```python
class Codec(Enum):
    JSON = "json"
    TOML = "toml"
    YAML = "yaml"
```

Hoy todos los artefactos son JSON. El campo existe igual porque agregarlo después sería un cambio incompatible del contrato `hpl/artifact-catalog/v4`, y el primer CLI con configuración en TOML o YAML lo va a necesitar.

Cada códec debe garantizar dos cosas: **serialización canónica** (mismo valor, mismos bytes, para que las huellas sean estables) y **preservación de lo ajeno** (las claves que HPL no escribió sobreviven intactas al ciclo de lectura y escritura).

#### Casos que parecen no entrar, y entran

| Caso | Forma |
|------|-------|
| Plugin `.ts`, prompt `.md`, skill con referencias | Uno o varios `FileArtifact` |
| Binario ejecutable | `FileArtifact` con `mode=0o755` |
| Agregar un ítem a un array de configuración | `ConfigKeyArtifact` con puntero terminado en `/-` |
| Servidor MCP | `ConfigKeyArtifact` con puntero `/mcp/<id>` |
| Un solo campo dentro de una definición existente | `ConfigKeyArtifact` con puntero al campo |

Regla de higiene: si aparece un caso que no entra en ninguna de las dos formas, es señal de que el adapter está intentando delegar lógica propia al motor. La solución es resolverlo en el adapter, no agregar una tercera forma.

### Artefactos propios del adapter

Casi todo lo que un adapter escribe viene del núcleo: recibe un descriptor y lo materializa. Pero hay archivos que existen **solo porque un CLI funciona como funciona**, y para esos no hay descriptor posible.

En OpenCode son los plugins escritos contra su API de plugins, el `package.json` y el lockfile de los que esos plugins dependen, la herramienta que uno de ellos invoca con su launcher, su plantilla de entorno, y un archivo de datos del propio adapter.

```python
def own_artifacts(self, environment: Environment) -> list[Artifact]: ...
```

Que un adapter tenga recursos propios de su tecnología es normal en puertos y adaptadores: un driver de base de datos lleva su gramática SQL, un adapter REST lleva sus serializadores, y el dominio no conoce ninguno de los dos. La invariante de la arquitectura es la **dirección de la dependencia** — el adapter conoce al núcleo, el núcleo no conoce al adapter — y no que todo lo que el adapter produce tenga que originarse en el núcleo.

El detalle que mantiene la flecha en su lugar: `own_artifacts` devuelve `Artifact`, un tipo del núcleo. El adapter aporta cosas propias, pero las entrega hablando el vocabulario que define el puerto, y el motor las materializa sin saber que son TypeScript ni que existe OpenCode.

**Es una puerta de escape, y las puertas de escape se abusan.** Dos candados la protegen:

| Candado | Qué impide |
|---------|------------|
| Contención, verificada por el registry | Que un adapter escriba fuera del `config_dir` de su propio CLI |
| La regla 2 como criterio de admisión | Que entre acá algo que podría tener forma agnóstica, vaciando el núcleo de a poco |

Si un archivo tendría sentido en un CLI que todavía no soportamos, va al núcleo. Usar `own_artifacts` para evitar escribir un descriptor es exactamente cómo se degrada esta arquitectura.

### Puertos secundarios

| Puerto | Responsabilidad | Por qué está separado |
|--------|-----------------|-----------------------|
| `FileSystem` | Escritura atómica, permisos, rutas de usuario, espacio | Windows y POSIX difieren; además hace testeable el motor sin tocar disco |
| `JournalStore` | Persistir y leer el journal de ownership | Permite tests con journal en memoria |
| `DependencyFetcher` | Materializar, verificar y probar MCPs | Aísla la red y la deja ocurrir solo en instalación |
| `ModelCatalog` | Proveedores y modelos disponibles | Es parte del adapter, no un puerto global: cada CLI resuelve modelos a su manera |

---

## Manifiesto de capacidades: falla cerrado

Cada adapter declara qué soporta. El registry **rechaza registrar** un adapter cuyo manifiesto no coincida con lo que realmente implementa. Un adapter mal escrito no arranca el programa; no falla a mitad de una instalación.

```python
@dataclass(frozen=True)
class CapabilityManifest:
    cli_id: str
    skills: bool = False
    system_prompt: bool = False
    slash_commands: bool = False
    sub_agents: bool = False
    prompts: bool = False          # el prompt del agente va en un archivo aparte
    mcp: bool = False
    per_agent_model: bool = False
    schema: str = "hpl/capability-manifest/v1"
```

Validaciones al registrar:

- [ ] `manifest.cli_id == adapter.id`
- [ ] Cada capacidad en `True` que se materializa como archivo tiene su ancla de `Layout` no nula
- [ ] Cada capacidad en `True` tiene su método `render_*` implementado
- [ ] Cada capacidad en `False` no expone ruta ni render (evita capacidades fantasma)
- [ ] `per_agent_model` en `True` implica los tres métodos de modelos
- [ ] No hay dos adapters con el mismo `id`

Este es el mecanismo que evita que la abstracción se degrade cuando se agregue el cuarto o quinto CLI.

**El ancla obligatoria solo aplica a capacidades basadas en archivos.** Los subagentes, los servidores MCP y la asignación de modelo pueden vivir dentro del archivo de configuración en un CLI y como archivos en otro. Exigirle un directorio a los dos obligaría a uno a declarar una ruta que nunca usa, que es la misma ficción que el chequeo de capacidades fantasma intenta evitar. Para esas capacidades la prueba de soporte es el render, no la ruta.

**Las capacidades sin ancla dedicada se validan solo por su render.** `mcp` y `per_agent_model` escriben adentro del archivo de configuración compartido, que también guarda claves de otras capacidades y del propio usuario. Que ese archivo exista no prueba que ninguna capacidad en particular esté soportada, así que exigirlo como ancla rechazaría adapters correctos: un CLI con archivo de settings pero sin soporte MCP sería acusado de exponer una capacidad fantasma.

**Los plugins no son una capacidad.** No hay categoría de contenido para ellos y no puede haberla: un plugin de OpenCode es TypeScript escrito contra su propia API, y no existe una forma agnóstica que sirva también para los hooks de Claude Code. Viajan por `own_artifacts`, y el manifiesto queda siendo lo que debe ser: un contrato sobre cómo sale el contenido del núcleo.

**El layout se prueba contra un home inexistente.** Construir un `Layout` tiene que ser aritmética de rutas pura. Si un adapter consultara el disco, el resultado del registro dependería del estado de la máquina: pasaría en la del desarrollador, donde el directorio del CLI ya existe, y fallaría en la de un usuario que instaló el CLI pero nunca lo abrió. El registry lo prueba contra un home que no existe, así que ese error se cae en el primer test.

---

## Detección de CLIs

Chequeo puro de sistema de archivos y PATH. **Sin ejecutar el CLI.** Ejecutar binarios de terceros para detectarlos es lento, falla en entornos restringidos y no es portable a Windows.

```python
@dataclass(frozen=True)
class Detection:
    installed: bool        # binario encontrado en PATH
    binary_path: Path | None
    config_dir: Path | None
    config_found: bool     # el directorio de config existe
```

Un CLI se considera presente si `installed or config_found`. Los dos casos importan: alguien puede tener config sin el binario en PATH (instalación en ubicación no estándar), o el binario sin haberlo corrido nunca.

El menú de instalación lista **solo CLIs soportados**. Un CLI instalado pero sin adapter no aparece.

---

## Journal de ownership v4

El journal es lo que hace a HPL aditivo: registra qué creó, para poder retirarse sin llevarse trabajo ajeno.

### Qué registra

- `after_digest` identifica qué es nuestro pero no decide si se pisa: instalar y desinstalar escriben todo lo que el journal reclama sin mirar la huella; volver atrás es trabajo del snapshot, no del journal.
- Hay una instalación por CLI, así que se puede tener HPL en dos CLIs con ciclos de vida independientes.
- Cada entrada de configuración se direcciona con un JSON Pointer, y el motor escribe rutas anidadas sin conocer el esquema.
- La asignación de modelo no pasa por el journal: vive en su propio store, así que pisar el artefacto no pone en riesgo el ownership.

### Formato

```json
{
  "schema": "hpl/journal/v4",
  "hpl_version": "7.7.8",
  "installs": [
    {
      "cli": "opencode",
      "installed_at": "2026-08-14T00:41:08Z",
      "release": {
        "version": "7.7.8",
        "content_digest": "sha256:1a2b…",
        "catalog_digest": "sha256:3c4d…"
      },
      "entries": [
        {
          "id": "skill:sdd-apply",
          "kind": "file",
          "target": "/home/user/.config/opencode/skills/sdd-apply/SKILL.md",
          "after_digest": "sha256:5e6f…",
          "mode": "0644",
          "ownership": "owned",
          "created_at": "2026-08-14T00:41:09Z"
        },
        {
          "id": "agent:sdd-apply",
          "kind": "config-key",
          "target": "/home/user/.config/opencode/opencode.json",
          "pointer": "/agent/sdd-apply",
          "after_digest": "sha256:7a8b…",
          "ownership": "owned",
          "created_at": "2026-08-14T00:41:09Z"
        }
      ],
      "links": [
        {
          "id": "cbm",
          "target": "/usr/local/bin/codebase-memory-mcp",
          "ownership": "non-owning-link"
        }
      ]
    }
  ]
}
```

### Dónde vive

```
$XDG_DATA_HOME/hpl/journal-v4.json     # 0600, en un directorio creado 0700
```

Sin `XDG_DATA_HOME` (o sin un valor absoluto) la ruta es `~/.local/share/hpl/journal-v4.json`. El directorio de datos lo resuelve el puerto `FileSystem` (`data_dir`), y el journal, los snapshots, las asignaciones de modelo y las dependencias materializadas cuelgan del mismo lugar. El nombre lleva la versión del esquema.

El directorio se **crea** con permisos `0700`. Si ya existía conserva los suyos: endurecerlo sería mutar algo que esta instalación no creó, y el archivo en `0600` ya protege el contenido.

Quien resuelve esa ruta es `FileJournalStore`, detrás del puerto `JournalStore`. Escribe a través del puerto `FileSystem`, así que la política del store —quién puede escribir, qué se puede escribir, qué significa un archivo dañado— se prueba sin un home real. Un journal ilegible **no** es un journal vacío: el store falla ruidosamente, porque tratarlo como vacío dejaría huérfano todo lo ya instalado.

### Lo que el desinstalador deja atrás

Retirar no reescribe un archivo de configuración si no cambió nada en él: la indentación del usuario es suya y no se gasta sin motivo.

Queda un residuo conocido y aceptado: si el archivo de configuración del CLI **no existía** antes de instalar, HPL lo crea y al desinstalar lo deja vacío (`{}`). El journal registra claves, no la existencia del archivo, así que no hay forma de saber que fue nuestro sin agregar una entrada para el archivo mismo — y esa entrada chocaría con las claves que viven adentro. Un archivo de configuración vacío es inofensivo: el CLI lo lee como configuración por defecto. Si alguna vez molesta, la solución es registrar la creación del archivo como un hecho aparte del de sus claves.

### Reglas invariantes

- [ ] Todo `target` está contenido dentro del home del usuario
- [ ] El journal lo escribe el usuario dueño del home, nunca root
- [ ] Escritura atómica: archivo temporal, `fsync`, `rename`
- [ ] Al desinstalar, todo lo que el journal reclama se borra sin mirar si el usuario lo tocó, salvo los appends, donde la huella no alcanza para decidir si el ítem sigue siendo nuestro y el resultado es `unaccounted` (ver "La excepción: punteros que agregan a una lista")
- [ ] Un `link` nunca se borra: HPL no es dueño de dependencias preexistentes
- [ ] Reinstalar nunca reduce lo que el journal ya poseía
- [ ] El journal se consulta antes de escribir el primer artefacto, no después del último

---

## Configuración de modelos

### De dónde salen proveedores y modelos

El adapter de OpenCode lee tres archivos. No levanta un servidor ni parsea salida del CLI.

| Fuente | Ruta | Aporta |
|--------|------|--------|
| Catálogo | `~/.cache/opencode/models.json` | Proveedores, modelos, costo, límites, `tool_call`, `reasoning` |
| Credenciales | `~/.local/share/opencode/auth.json` | Qué proveedores tienen sesión OAuth |
| Config | `~/.config/opencode/opencode.json` → clave `provider` | Proveedores personalizados del usuario |

Un proveedor se ofrece si cumple **alguna** de estas condiciones:

- Tiene credencial en `auth.json`
- Tiene todas sus variables de entorno seteadas (`ANTHROPIC_API_KEY`, etc.)
- Está declarado como proveedor personalizado en la config
- Es el proveedor integrado del propio CLI

De cada proveedor se ofrecen **solo los modelos con `tool_call: true`**. Un modelo sin tool calling no puede ejecutar una fase SDD.

Si el archivo de catálogo no existe todavía (el usuario instaló el CLI pero nunca lo abrió), el adapter devuelve catálogo vacío y la TUI explica qué hacer. No es un error.

### Modelo de asignación

```python
@dataclass(frozen=True)
class ModelAssignment:
    provider_id: str      # "anthropic"
    model_id: str         # "claude-sonnet-5"
    effort: str | None    # None = default del proveedor
```

Se persiste como `provider/model`, más un campo de esfuerzo cuando el modelo declara variantes de razonamiento.

### Estado inicial

Ningún agente trae modelo asignado. La tabla arranca con todos en "sin modelo", y un agente sin configurar simplemente no tiene el campo. Esto preserva la política vigente de no fijar modelos por agente: configurar es una decisión explícita del usuario, y siempre reversible.

### El prompt de un agente es corto

Un prompt de agente lleva solo lo que ese agente no puede permitirse ignorar aunque nunca llegue a leer nada más: su identidad, sus innegociables y su contrato de salida. Todo lo procedimental — la secuencia de pasos, las plantillas de salida, los protocolos, los gates — vive en la skill de esa fase y el orquestador se la pasa como ruta al delegar.

La razón es medible: diez prompts de fase SDD que fueran copias completas de su skill sumarían unos 24.700 tokens (98.791 bytes en las diez `SKILL.md`, a 4 bytes por token) que entrarían en contexto antes de que el agente hiciera nada, mientras que `sdd-verify`, que lleva sólo identidad, innegociables y contrato de salida, gasta unos 480 tokens (1.919 bytes de cuerpo, mismo criterio) para el mismo tipo de trabajo. Y como el orquestador además le pasa al subagente la ruta de su propia skill, un prompt que ya es esa skill hace que el agente lea otra vez lo que ya tiene.


De ahí sale una regla de contenido: **un descriptor de agente cuyo cuerpo supere unos pocos párrafos indica que hay procedimiento donde debería haber identidad.**

### Qué es el system prompt y qué es un agente

Hay dos cosas distintas: las reglas y protocolos que obligan a cualquier agente, y la personalidad y el rol de un agente en particular. Se separan:


| Parte | Va a | Alcance |
|-------|------|---------|
| Reglas de trabajo, alcance de persona, carga contextual de skills, protocolo de memoria persistente, cierre de sesión | `system-prompt/` | Todos los agentes, en toda sesión |
| Idioma de la respuesta: cuál usar y cuándo no cambiarlo | `system-prompt/` | Todos los agentes, en toda sesión |
| La voz, en sus ocho secciones: `Rules`, `Personality`, `Language`, `Speech patterns`, `Tone`, `Philosophy`, `Expertise`, `Behavior` | `agents/king-hpl.md` | Ese agente |

El criterio no es "reglas arriba, estilo abajo": es a quién obliga cada cosa. La mayoría de las reglas de trabajo — no agregar atribución de herramientas a un commit, verificar antes de afirmar — tienen que obligar a cualquier agente, no solo al que casualmente cargaba ese archivo como prompt. Pero una regla sobre cómo trabaja una voz en particular es de esa voz: `Work out loud or not at all` vive en `king-hpl.md` a propósito, porque como regla global sería falsa — los agentes implementadores escriben en silencio para satisfacer una spec, y eso es exactamente lo que se les pide. Otro caso: una prohibición global de compilar habría contradicho la skill `sdd-verify`, que exige correr el build y registrar su hash.


`Language` se parte por esa misma razón. La mitad neutral — en qué idioma responder, cuándo no cambiarlo, que una respuesta en inglés sea inglés hasta en el saludo — obliga a todos los agentes y vive en `system-prompt/`; el color — Rioplatense con voseo, la misma calidez en inglés — es de esa voz y se queda en su archivo.

### Agentes configurables

Todos los agentes que HPL distribuye aceptan un modelo propio: los 10 de la línea SDD, los dos de coordinación y los cuatro especialistas sin fase.

```
sdd-init      sdd-explore    sdd-propose    sdd-spec      sdd-design
sdd-tasks     sdd-apply      sdd-verify     sdd-archive   sdd-onboard
hpl-orchestrator   king-hpl
hpl-explorer  hpl-general    hpl-implementer  hpl-verifier
```

---

La TUI se dibuja con `curses`, de la biblioteca estándar. No agrega ninguna dependencia, y por lo tanto no agrega nada que fijar con hash ni sumar al zipapp. Las pantallas que siguen son listas verticales con un cursor y teclas de una letra: no piden color, ni layout anidado, ni nada que justifique traer un paquete —y menos uno que arrastre un segundo— para dibujarlas.


### Menú principal

La pantalla se dibuja en inglés — el idioma de todo el texto de la TUI, sin excepción para esta pantalla ni ninguna otra.

```
HPL 7.7.8

  ▸ Install
    Update
    Upgrade
    Configure models
    Grant MCP servers
    Status and diagnostics
    Uninstall
    Exit
```

### Instalar

Detecta CLIs soportados y presentes. Selección de a uno.

```
Where would you like to install HPL?

  ▸ OpenCode          ~/.config/opencode        full
```

Elegido el CLI, muestra la vista previa —el mismo reporte que produce `install --dry-run`, con un aviso explícito de que todavía no se escribió nada— y sólo confirmarla cruza el punto sin retorno:

```
Install · OpenCode

PREVIEW — nothing has been written yet.

...

enter: install now · esc: back, nothing written
```

No hay confirmación por dependencia individual dentro de la TUI: qué servidores MCP entran ya se decidió con `--mcp` antes de llegar a esta pantalla (ver "Paridad con flags").

### Estado y diagnóstico

Muestra el mismo reporte que `doctor --json`. Desde acá, y sólo acá, se llega a `restore`: elegir la única acción de esta pantalla abre la lista de generaciones de snapshot que todavía se pueden leer. No hay una entrada de `restore` en el menú principal — es una acción sobre lo que el diagnóstico ya mostró, no una entrada propia.

### Desinstalar

Selecciona, de los CLIs donde el journal registra una instalación propia, cuál desinstalar. La confirmación es una vista previa de qué se va a borrar (resumida si son muchos ítems), con el cursor abierto por defecto sobre "Cancel": la opción destructiva nunca es la que queda seleccionada al entrar a la pantalla.

```
Uninstall · OpenCode

About to remove 3:
  skill:sdd-apply → ...
  agent:sdd-apply → ...
  ...

  ▸ Cancel — leave it installed
    Confirm — remove it
```

`restore`, alcanzado desde "Estado y diagnóstico", pide la misma confirmación con el cursor sobre "Cancel".

### Configurar modelos

Cuatro pasos, con opción de volver en cada uno, y todo lo elegido queda **acumulado** en la propia pantalla hasta que se confirma de una sola vez -- no hay una escritura por cada asignación.

```
CLI → agente → proveedor → modelo → [esfuerzo]
```

Terminar la caminata (un modelo llano, o un modelo de razonamiento más su esfuerzo) no escribe nada: guarda la elección en el estado de la propia pantalla y vuelve a la lista de agentes, igual que tildar una fila no escribe nada en `McpSelectionScreen`. `d` hace lo mismo del otro lado: en vez de sacar la asignación ahí mismo, la marca para sacarla. La lista de agentes muestra las dos cosas por separado -- lo que ya está aplicado y lo que está pendiente de confirmar -- y una fila `Confirm` después del último agente es la única que efectivamente escribe: aplica todo lo acumulado, asignaciones y remociones por igual, en un solo `cli.models_apply`, y por lo tanto un solo `install()` y una sola generación de snapshot.

```
Models · OpenCode

  Agent                    Current model                Staged change
  ▸ hpl-orchestrator   (no model)
    sdd-apply              anthropic/claude-sonnet-5 · high  → anthropic/fast-model
    sdd-verify             (no model)                   → (remove)
    …
    Confirm — apply staged changes

  enter: configure, or confirm to apply · d: stage a removal · esc: back, discards staged changes
```

Salir sin confirmar (`esc` en la lista de agentes) descarta todo lo acumulado: el footer ya lo dice, y no hace falta ningún otro aviso porque nada llegó a escribirse. Configurar cuatro agentes en una sola sentada es, ahora, un `install()` y una generación -- antes eran cuatro de cada uno, con cuatro avisos de activación por separado, exactamente la misma tormenta que `McpSelectionScreen` ya resolvió para su propio Continue.

### Paridad con flags

La TUI no puede hacer nada que los flags no puedan. Esta regla protege `INSTALL_BY_AGENT.md`, que es el diferencial de HPL: instalación conducida por un agente.

```bash
hpl                                          # TUI
hpl install --cli opencode --mcp context7 --mcp engram
hpl models set --cli opencode --assign sdd-apply=anthropic/claude-sonnet-5 --effort sdd-apply=high
hpl models unset --cli opencode --agent sdd-apply
hpl uninstall --cli opencode
hpl doctor --json
```

Un test de contrato verifica que cada acción de la TUI tenga su comando equivalente.

#### Qué existe hoy

Diez subcomandos: `install`, `update`, `upgrade`, `uninstall`, `repair`, `doctor`, `restore`, `models`, `mcp` y `directory`, con `--json` en todos y `--dry-run` en `install`, `update`, `upgrade` y `repair`; `-V` / `--version` responde antes del subcomando y no abre nada. `mcp` y `directory` tienen su propia sección más abajo, y `update` y `upgrade` separan actualizar *la instalación* de actualizar *el programa*.


- `install --cli <id>` acepta `--mcp ID[=CLAVE]` (repetible): un servidor no nombrado no se instala, y la forma con clave concede sus herramientas y embarca su convención contra un servidor que la instalación ya corre bajo esa clave, sin obtener ni configurar nada.
- `update --cli <id>` reaplica la selección que esa instalación ya tiene registrada —servidores atados incluidos, más las claves y los directorios otorgados—, sin ningún flag de selección. No hay una segunda implementación de colocar artefactos: reconstruye qué habría sido `--mcp` leyendo el journal y delega en `install`.
- `upgrade` es el único que no lleva `--cli`, porque no toca la instalación de ningún CLI: reemplaza el propio binario `hpl` en ejecución por el último publicado, verificando el checksum antes de un único rename atómico.
- `uninstall --cli <id>` retira lo que el journal reclama para ese CLI.
- `repair --cli <id>` quita los riesgos del journal que `doctor` sólo nombra (entradas de directorio en cuarentena); con `--dry-run` informa qué quitaría sin escribir nada.
- `doctor` acepta `--start-mcp-servers`, la única forma en que deja de ser de sólo lectura.
- `restore [generación]` tampoco lleva `--cli`: una generación es lo que tocó un comando, no la instalación de un CLI.
- `models set` / `models unset` / `models list` asignan, quitan y listan el modelo de un agente.
- `mcp grant` / `mcp revoke` / `mcp list` manejan las claves de servidores MCP que la persona administra por su cuenta, parejo para todos los agentes.
- `directory grant` / `directory revoke` manejan un directorio de trabajo fuera del worktree, también para todos los agentes.

Cada reporte declara su esquema `hpl/cli-report/v1`.

Seis cosas que la CLI hace y conviene no perder:

- **Pregunta antes de hacer.** El journal se consulta con `ensure_writable()` **antes** del primer artefacto. Una negativa descubierta al final llegaría con los artefactos ya en disco y sin registro: una instalación que existe y no se puede desinstalar, el peor resultado que este motor puede producir. Preguntar primero lo convierte en un mensaje y un home intacto.
- **El preflight pregunta las dos cosas: si se puede escribir y si se puede leer lo que ya hay.** Un journal que no se puede leer es uno que no se puede extender, y descubrirlo después de colocar los artefactos los dejaría en disco sin nada que los registre — con `doctor` fallando contra ese mismo journal ilegible, así que no quedaría forma de enterarse de que están.
- **`ensure_writable()` es un preflight, no una garantía.** Rechaza root y homes ajenos, que son las causas previsibles. No puede prometer que el guardado posterior funcione: el disco se puede llenar, los permisos pueden cambiar entre medio, puede haber cuota. Por eso el camino de falla al registrar tiene que ser correcto igual, y no solo improbable.
- **Si igual no se puede registrar, se retira lo instalado.** Y se informa lo que no pudo volver atrás: HPL posee claves dentro de un archivo de configuración, nunca el archivo, así que uno que tuvo que crear sobrevive vacío. Inofensivo, pero afirmar un deshecho limpio sería una mentira chica en el único reporte que alguien lee cuando algo ya salió mal.
- **El rollback deshace esta corrida, nunca lo que corridas anteriores ya poseían.** Hay dos vistas de la misma instalación y confundirlas sale caro: la **acumulada** es la que se registra —todo lo que ese CLI posee, viejo y nuevo— y la **colocada** es solo lo que esta corrida escribió. Solo la segunda puede tocarse al deshacer. Una reinstalación no crea nada, así que no hay nada que deshacer; retirar la vista acumulada borraría una instalación que funciona mientras el journal —que no se llegó a escribir, porque escribirlo es lo que falló— sigue afirmando que está entera. Es la misma mentira que los artefactos huérfanos, apuntando para el otro lado.
- **Reinstalar no reduce lo que el journal ya poseía.** La segunda corrida no crea nada, porque todo lo que quiere ya está: su propio trabajo de la primera. Reemplazar el registro con ese resultado vacío dejaría huérfanos para siempre todos los artefactos que la primera corrida colocó —119 en una instalación en OpenCode sin ningún MCP seleccionado, medida con `hpl install --cli opencode --dry-run --json` contra un HOME descartable (campo `created`); el número crece con la selección y cambia con cada release, que es justamente por qué el argumento no depende de él—, sin nada que pruebe que fueron nuestros. Las entradas previas se conservan y las nuevas se suman.

#### Actualizar es reinstalar, y `update` es reinstalar sin tener que repetir la selección

`hpl update --cli <id>` no tiene un mecanismo propio: sigue siendo `install` por debajo. Lo que agrega es no tener que recordar la selección: un `install` a secas no nombra ningún servidor, y un servidor no nombrado se retira, así que actualizar con `install` exige repetir exactamente los `--mcp` de la primera vez, y la selección de un servidor *atado* ni siquiera se puede leer de vuelta desde la configuración renderizada, porque una atadura no escribe `/mcp/<id>` ahí. `update` reconstruye esa selección desde el journal y delega (`update`, `src/hpl/cli.py`).


Lo que sigue vale para los dos, porque los dos terminan en el mismo planner, que distingue las tres respuestas posibles por artefacto (`planner.plan`, `_file_step`/`_key_step`, `src/hpl/core/planner.py`).

- **El contenido cambió bajo el mismo id:** se reescribe. Una dirección que el journal reclama se pisa sin preguntar si el usuario la tocó, y sólo se escribe si lo que hay ahora difiere de lo que se quiere: `_file_step` compara el digest (y el modo, para un ejecutable) contra lo leído del disco, y sólo devuelve `UPDATE` cuando discrepan.
- **El contenido es idéntico:** se deja quieto. Mismo digest y mismo modo es `UNCHANGED`; reinstalar no repite una escritura que no hace falta.
- **La dirección está ocupada por algo que el journal no reclama:** es colisión, y se saltea. `_file_step` devuelve `SKIP` cuando no hay entrada del journal para esa ruta, o la entrada es de otro tipo o apunta a otro destino — la única situación en la que reinstalar de verdad se niega a escribir.

Un artefacto que un release más nuevo **deja de embarcar** sí se retira. `planner.retirements` calcula, para cada entrada que el journal ya tiene, si el render de esta corrida todavía la pide; la que no aparece entre los artefactos actuales es una diferencia de conjuntos por id, sin tocar disco (`retirements`, `planner.py`). `cli._install` pasa ese conjunto — menos las entradas `dependency-tree`, que se recalculan aparte contra los servidores MCP que la corrida efectivamente mantiene — a `planner.retire`, que sí borra: un archivo se quita si existe, una clave se saca del documento, y cada handler por tipo marca el id como `removed` (`retire`, `_retire_files`, `RETIRE_HANDLERS`, `planner.py`; el llamado desde `cli.py` alrededor de la variable `retirements`). El journal se actualiza para reflejar sólo lo que `retire` confirmó haber sacado, nunca la intención: un id que no pudo confirmarse sigue en el journal para que una corrida posterior termine el trabajo.

Lo que sí es una edición a mano del usuario sobre una dirección que HPL posee: se reescribe igual — esa política no distingue este caso de cualquier otro `UPDATE`, así que el producto gana sin pedir permiso —, pero desde que existe `Plan.overwritten` deja de ser silencioso. Decidir `UNCHANGED` contra `UPDATE` ya obliga a leer la dirección, así que el paso carga lo que encontró ahí (`found`), y que eso discrepe del digest que el journal tenía registrado (`entry.after_digest`) es exactamente la definición de una edición a mano — la misma comparación que `doctor` llama drift, hecha en el momento en que la edición está por gastarse en vez de antes o después. `Plan.overwritten` filtra los `updates` con esa forma, y tanto `install` como `--dry-run` lo reportan aparte, a tiempo para que alguien cambie de idea en el dry run y a tiempo para saber qué se perdió después de uno real. Lo que protege ese contenido no es un chequeo que impida la escritura — no lo hay — sino el snapshot que se toma antes de escribir: `restore` puede devolver la versión de la persona, dentro de la ventana que la retención de 20 generaciones guarda. Los `append` quedan afuera de este reporte a propósito: se los localiza por el digest registrado, así que un valor que discrepa no se encuentra ahí y "alguien editó el nuestro" es indistinguible de "alguien borró el nuestro y agregó el suyo".

#### Una inconsistencia conocida

`detect()` es la única operación de disco que **no pasa por el puerto `FileSystem`**: el adapter resuelve con `shutil.which` contra el PATH y un `is_dir()` real. Eso hace que la detección mire la máquina donde corre, sin importar lo que se le diga al puerto, y que no se pueda probar sin tocar el disco de verdad. Arreglarlo cambia la firma de `CliAdapter.detect` y el puerto necesitaría saber buscar en el PATH, así que es una unidad de trabajo aparte.

---

## Estructura del repositorio

```
hpl/
├── pyproject.toml
├── src/hpl/
│   ├── __main__.py
│   ├── cli.py                     # flags, modo desatendido; raíz de composición
│   ├── predecessors.py            # productos anteriores que ocupan la misma configuración
│   ├── identity.json              # nombre, versión y fuente de releases de la distribución
│   ├── core/                      # ningún módulo con nombre de CLI adentro
│   │   ├── content.py             # carga y valida el núcleo de contenido
│   │   ├── types.py               # descriptores, Artifact, Layout, Detection
│   │   ├── registry.py            # registro de adapters, falla cerrado
│   │   ├── planner.py             # plan, apply, retire, rollback
│   │   ├── journal.py             # journal v4
│   │   ├── ownership.py           # huellas, colisiones
│   │   ├── snapshot.py            # lo que había antes de escribir
│   │   ├── dependencies.py        # materializar un servidor `download` o `npm`
│   │   ├── mcp_handshake.py       # el `initialize` y la clasificación de su respuesta
│   │   ├── model_assignments.py   # preferencias de modelo por agente
│   │   ├── model_catalog.py       # qué modelos alcanza esta máquina
│   │   ├── catalog.py             # el catálogo embarcado
│   │   ├── codecs.py              # JSON, TOML, YAML como un solo puerto
│   │   ├── pointer.py             # direcciones dentro de un documento
│   │   ├── frontmatter.py         # el parser propio, sin dependencias
│   │   ├── placeholders.py        # el vocabulario cerrado que un cuerpo puede pedir
│   │   ├── identity.py            # la identidad de producto
│   │   ├── upgrade.py             # actualizar el programa
│   │   ├── foreign_loads.py       # lo que una CLI carga de otra
│   │   ├── credential_transport.py# la capacidad de transporte de credenciales
│   │   ├── engram_port.py         # la regla del puerto de engram por usuario
│   │   └── listeners.py           # quién escucha en un puerto, desde /proc
│   ├── ports/                     # cli_adapter, filesystem, journal_store, snapshot_store,
│   │                              # model_assignment_store, downloader, npm_installer, mcp_process
│   ├── adapters/
│   │   ├── opencode/              # adapter, layout, render, models, manifest, naming, assets/
│   │   └── claudecode/            # adapter, layout, render, manifest, assets/
│   ├── infra/                     # una implementación real por puerto, POSIX
│   ├── tui/
│   │   ├── app.py
│   │   ├── navigator.py           # las pantallas y el paso entre ellas
│   │   ├── session.py
│   │   ├── view.py
│   │   └── wordmark.py
│   └── content/                   # el núcleo, agnóstico
│       ├── skills/
│       ├── agents/
│       │   └── mcp/               # la mitad ambiente de cada servidor, y sus overrides
│       ├── commands/
│       ├── mcp/                   # un descriptor por servidor, con su convención adentro
│       ├── security/              # el catálogo de detección de credenciales
│       └── system-prompt/
│           └── mcp/               # la mitad ambiente, para el prompt de sistema
├── tools/
│   ├── build_catalog.py
│   ├── build_zipapp.py            # empaqueta el paquete en el zipapp ejecutable
│   ├── build_installer.py         # genera install.sh por identidad
│   ├── build_release_evidence.py  # certifica el zipapp y su checksum contra el commit
│   ├── verify_release_assets.py
│   ├── check_dependency_updates.py
│   ├── check_docs_links.py
│   └── hpl_skill_registry.py
├── tests/
└── docs/
```


El contenido vive dentro del paquete, alineado con la decisión previa de una única fuente canónica bajo `src/`. Eso permite distribuirlo como paquete sin rutas relativas frágiles.

---

## Contratos versionados

Cada contrato tiene esquema propio y versión. Un cambio incompatible sube la versión; el motor rechaza lo que no reconoce.

| Contrato | Esquema | Qué fija |
|----------|---------|----------|
| Manifiesto de capacidades | `hpl/capability-manifest/v1` | Qué soporta cada adapter |
| Catálogo de artefactos | `hpl/artifact-catalog/v4` | Salida generada del render, con huellas |
| Journal de ownership | `hpl/journal/v4` | Estado de instalación |
| Asignación de modelo | `hpl/model-assignment/v1` | Proveedor, modelo y esfuerzo por agente |
| Reporte de la CLI | `hpl/cli-report/v1` | Salida JSON de `install`, `uninstall` y `doctor` |

La forma de skills, agentes, comandos, prompts, MCPs y políticas la valida el cargador de contenido (`hpl.core.content`), no un esquema versionado con identificador de cable propio: no hay ningún `hpl/content-descriptor/vN` que ningún código emita o valide, así que esta tabla no vuelve a listarlo.

---

## Postura de seguridad

| Garantía | Cómo se sostiene |
|----------|------------------|
| Instalación aditiva: nunca pisa archivos del usuario que el journal no reclama | Una dirección ocupada por algo que el journal no reclama es una colisión y se saltea |
| Payload verificado con SHA-256 | Sobre el catálogo generado, que se reconstruye desde el contenido |
| Dependencias con versión fija, sin `npx` ni `latest` | El descriptor fija versión e integridad, y se verifican antes de colocar el artefacto |
| Sin ejecución como root | `ensure_writable()` rechaza root y homes ajenos antes de escribir |
| Rollback | El snapshot tomado antes de escribir; tiene un horizonte: pasada la retención, el original ya no está en ningún lado |
| Sin dependencias de terceros | Biblioteca estándar de Python; no hay nada que fijar con hashes |
| Detección sin ejecutar binarios de terceros | Chequeo de sistema de archivos y PATH |

La verificación de integridad del payload no se escribe a mano: el catálogo se genera y la suite falla si el catálogo commiteado no coincide con el generado desde el contenido.

---

## Fuera de alcance

- **Windows.** La arquitectura lo habilita (`FileSystem` como puerto, TUI portable, Python multiplataforma), pero no se entrega.
- **Otros CLIs.** Hay adapters para OpenCode y Claude Code; agregar otro es escribir un directorio bajo `adapters/` y registrarlo. Codex no tiene adapter.
- **Skills personales del autor.** Quedan fuera del payload.

---

## Riesgos conocidos

| Riesgo | Mitigación |
|--------|------------|
| El catálogo de modelos del CLI puede no existir todavía | Catálogo vacío no es error; la TUI explica cómo poblarlo |
| El formato de config del CLI puede cambiar entre versiones | El adapter concentra el daño; solo se toca un directorio |
| Dependencias Python amplían la superficie de ataque | Versiones y hashes fijos, verificados en instalación y en CI |
| Un adapter futuro puede declarar capacidades que no cumple | El registry falla cerrado al registrar |

---

## Decisiones de diseño del motor

### Actualizar una instalación existente

El planner responde dos preguntas por artefacto: si algo ocupa la dirección, y si el journal la reclama como propia. Lo que el journal reclama se sobrescribe, y sólo si el contenido nuevo difiere del que ya está: si es idéntico no es trabajo, y se deja quieto.

Dos preguntas no se hacen: si el artefacto fue cambiado a propósito desde entonces, y si los bytes que hay son los que el journal registró. Lo que el usuario haya reescrito sobre una dirección nuestra se pisa, y lo que lo protege es la copia que se toma antes de escribir, no una huella que se consulta al escribir.

Un append es la versión difícil de la pregunta. No tiene dirección propia, así que su item se busca por huella y el valor nuevo lo reemplaza donde está: appendear en su lugar dejaría dos nuestros y correría los del usuario. Un item que la lista ya no tiene vuelve a ser una creación — la ausencia no es un veredicto.

El rollback distingue las dos colocaciones: una creación se deshace removiendo, una actualización restaurando la versión anterior.

### Distribución de MCPs

Ningún binario de MCP se vendoriza ni se compila desde este repositorio: sostener la compilación para varios pares SO/arch es exactamente el costo que este diseño evita. **No vendorizar significa que la release no lleva binarios ajenos, no que no se descargue nada**: la descarga ocurre en la máquina del usuario, durante la instalación, y nunca después.

Sobre cualquiera de los mecanismos van las dos garantías que no se relajan: **versión fija, nunca `latest`**, e **integridad verificada antes de dejar el artefacto en su lugar**. La primera la sostenemos nosotros en el descriptor, siempre. La segunda depende del mecanismo, y el diseño lo dice en voz alta en vez de fingir uniformidad.

#### Tres formas, declaradas por el descriptor

Los MCPs del producto no se distribuyen todos igual, y forzarlos a un mecanismo único sería inventar un problema. El descriptor declara cuál le toca a cada uno.

| Forma | Qué hace la instalación | Integridad | Red al arrancar el agente |
|-------|-------------------------|------------|---------------------------|
| `remote` | Escribe una URL en la configuración del CLI | La del endpoint | Sí, por naturaleza: el servidor es remoto |
| `npm` | Materializa el paquete pineado en el directorio propio de HPL | La cadena del registry: hash de integridad del tarball y, cuando existe, atestación de provenance | Ninguna |
| `download` | Baja el activo del par SO/arch y verifica su SHA-256 contra el checksum publicado | Nuestra, obligatoria, fail-closed | Ninguna |

Que la integridad de la forma `npm` la sostenga el registry y no nosotros es una decisión, no un descuido: verificar un hash propio exigiría materializar el paquete a mano y renunciar a una cadena que ya hace ese trabajo mejor —y que, en el caso de los paquetes que envuelven un binario nativo, lo verifica una segunda vez contra el checksum de su propio release.

#### Por qué el comando configurado nunca es `npx`

La tentación es escribir `npx --package=<paquete>@<versión>` como comando del servidor y darlo por resuelto: es una línea de texto y no descarga nada en la instalación. Precisamente por eso no sirve. **`npx` no es un paso de instalación: es un paso de arranque.** El paquete se resuelve la primera vez que el CLI anfitrión spawnea el servidor, y vuelve a consultarse en cada arranque posterior.

Medido con una versión exacta y una caché de npm dedicada: con la caché fría, el primer arranque tarda nueve segundos y deja setenta y dos megabytes. Con la caché caliente arranca en poco más de un segundo. Pero con la caché caliente, la versión exacta ya resuelta y el registry inalcanzable, **`npx` se cuelga un minuto y medio y después falla**. La caché no lo vuelve autosuficiente; solo el modo offline explícito lo hace, y ese modo depende de una caché que no es nuestra y que el usuario puede borrar con una orden.

Un MCP que necesita la red para arrancar traslada el riesgo desde la instalación —donde hay una persona mirando, un reporte y un rollback— hasta el arranque del agente, que es el peor lugar posible para descubrirlo. Por eso el paquete se materializa en instalación y la configuración apunta al binario resuelto por ruta absoluta.

#### Dónde vive HPL

HPL tiene un directorio propio de datos, que el puerto `FileSystem` resuelve (`FileSystem.data_dir`): `$XDG_DATA_HOME/hpl/` con fallback a `~/.local/share/hpl/`. El journal, los snapshots, las asignaciones de modelo y lo que se baja cuelgan de ese único lugar; `journal_store_file.py`, `snapshot_store_file.py` y `model_assignment_store_file.py` lo resuelven a través del puerto.

Las dependencias cuelgan de `<data_dir>/mcp/<nombre>/<versión>/`, con la versión en la ruta: actualizar es colocar al lado y retirar lo viejo, que es la forma que el motor ya sabe ejecutar.

El catálogo y el registry aceptan dos territorios: el `config_dir` del CLI anfitrión y el directorio propio de HPL (`catalog.Territory` reconoce `config_dir` y `CANONICAL_DATA_DIR`). El chequeo de `registry` sobre `own_artifacts` queda a propósito ceñido al `config_dir` del adapter: una dependencia la coloca el motor, nunca un adapter, así que ensanchar ese guard no cerraría ningún hueco real.

**Lo que baja es un artefacto nuestro como cualquier otro**: entra al journal (el tipo `dependency-tree`, que `planner._retire_dependency_trees` retira al desinstalar), tiene digest y se retira con rollback. Escribirlo en un directorio compartido del sistema sería reclamar una dirección que no es nuestra, y el planner tendría razón en negarse.

La forma `download` baja el activo con su SHA-256 verificado antes de que el archivo llegue a su lugar, y extrae un `.tar.gz` con guarda contra miembros que se escapan del directorio (`core/dependencies.materialize`; `engram` se instala así, con checksum y `archive_members` fijados en su descriptor). La forma `npm` corre `npm ci` contra un lockfile que sintetiza para un único paquete (`core/dependencies.materialize_npm`).

#### La plataforma no soportada se rechaza

Si el par SO/arch que corre no está entre los que el descriptor declara, la instalación se rechaza y lo dice. No hay tabla de degradaciones ni instalación parcial silenciosa: una instalación a medias es peor que una que no ocurrió, porque miente sobre lo que dejó.

#### El usuario elige, y el contenido se adapta por ausencia

Cuáles MCPs se instalan lo decide el usuario. La paridad que el resto del producto exige se sostiene sin construir la TUI acá, porque **la selección no vive en ninguna superficie**: es una función pura del núcleo que recibe el contenido y los ids elegidos y devuelve el contenido que sobrevivió. Las flags y la TUI la llaman igual, sin agregarle nada.

Que la selección se aplique una sola vez, en el núcleo y antes de renderizar, no es una comodidad: un adapter renderiza un ítem a la vez y nunca ve el árbol completo, así que un render por ítem no podría saber qué eligió el usuario ni aunque quisiera. Aplicarla una vez es lo que deja a todos los adapters —y a cualquier superficie futura— sin enterarse de que hubo una elección.
**Una herramienta que llega con un MCP no puede ser un requisito.** Si el usuario elige qué servidores se instalan, declarar una de sus herramientas como requerida nombra una condición que algunas instalaciones no pueden cumplir nunca. Esas herramientas van entre las opcionales, donde declinar el servidor significa simplemente que la herramienta no se concede.

Un MCP que no se seleccionó no puede quedar mencionado como si estuviera. Eso se resuelve sin condicionales en la prosa: un servidor se concede sólo si viaja, y **el cuerpo del descriptor de cada MCP es su convención**, así que si el MCP no se selecciona su convención tampoco se embarca: es el mismo artefacto, no dos que hay que mantener sincronizados.

La prosa de las convenciones ya está escrita defensiva —dice qué hacer cuando la referencia no está, en vez de asumirla— y la que todavía no lo esté se pasa a esa forma. Es más barato que sostener contenido condicional, y no le pide a la revisión adversarial que juzgue prosa con ramas, que es donde fabrica contradicciones.

#### Un agente declara servidores, no las herramientas que traen

`optional_tools` significaba dos cosas a la vez: herramientas nativas del CLI y herramientas que sólo existen porque un servidor está instalado. `sdd-explore` lo mostraba en una sola línea —`optional_tools: [write, codebase-memory]`— donde `write` es nativa y la otra llega con un MCP. Un campo, dos conceptos, y ninguna regla que pudiera distinguirlos sin adivinar.

Se separan. `requires_tools` y `optional_tools` nombran **sólo herramientas nativas**; `optional_mcp` nombra **ids de servidor**, y no lo escribe el agente: lo deriva el cargador de las listas `reaches` de los descriptores. Y no hay `requires_mcp`: un servidor que el usuario puede declinar no puede ser un requisito, y ahora eso es estructural en vez de una regla sostenida por un test — no hay campo donde escribirlo.

Tres cosas se caen solas con la separación:

- **El permiso deja de ser una tabla y pasa a derivarse.** El adapter escribe cada servidor en `/mcp/<id>`, así que el id *es* la clave que el CLI usa para nombrar sus herramientas, y el patrón de permiso es esa misma clave con el comodín. La tabla de traducción del adapter vuelve a nombrar sólo herramientas nativas.
- **El descriptor no declara qué herramientas provee.** Nadie lo leería: el agente nombra el servidor y el permiso sale del id. Un campo sin lector es documentación que se desincroniza en silencio.
- **Un id que ningún descriptor provee es un error de carga**, no una herramienta que se deja de conceder sin que nadie avise.

#### Invariantes en los dos bordes

La misma idea aplicada dos veces, en los dos lugares donde una tabla tiene que cubrir un enum: el catálogo verifica al importar que toda capacidad no interactiva tenga fuente, y el adapter verifica al importar que toda forma de distribución tenga traducción. Los dos con `if` y `raise`, no con `assert`: `python -O` borra los `assert`, y un invariante que desaparece bajo optimización desaparece exactamente en producción.

Sin el segundo, agregar `npm` al núcleo en 8b habría renderizado un servidor npm como si fuera remoto, en silencio. Con él, no se puede ni importar el módulo hasta que el adapter sepa qué hacer.

#### La convención aterriza donde ya viven las convenciones

El cuerpo del descriptor se escribe en `_shared/mcp/<id>-convention.md`, que cuelga del mismo `_shared/` donde viven las convenciones escritas a mano y donde el contenido embarcado las referencia por su ruta. Sin placeholder nuevo, sin ancla de layout nueva.

El subdirectorio propio no es cosmético. `_shared/` tiene convenciones escritas a mano, y un id de servidor puede coincidir con el nombre de una de ellas. Si la convención de un servidor cayera en el mismo espacio de nombres plano, un id que coincidiera con uno de esos stems pisaría un archivo con el que no tiene nada que ver. `mcp/` como subdirectorio propio no detecta esa colisión al construir el catálogo: la vuelve imposible de escribir.

Eso resuelve el alcance sin condicionales en la prosa y sin conocimiento cruzado. **La referencia es siempre la misma frase; lo condicional es el archivo.** Si el servidor no se eligió, el archivo no se escribe, la cláusula defensiva se activa, y ningún agente leyó una convención que no le tocaba. La alternativa —enlazar la convención globalmente, como hace el prompt de sistema— se descartó: le habría mandado la convención de cada servidor a los doce agentes, que es el mismo defecto que esta unidad viene a corregir.

#### Node es precondición de instalación

La forma `npm` se resuelve con `npm ci --ignore-scripts` contra un lockfile fijado, y eso exige un Node en el PATH del usuario. HPL lo verifica y lo dice cuando falta; no lo instala: instalar un runtime completo es otro problema de seguridad, y haría que la unidad que distribuye MCPs además distribuya lenguajes.

#### El retiro es genérico

Retirar lo que el journal reclama y el render ya no produce no sabe qué es un MCP: la regla es general, y `planner.retirements(installed, artifacts)` es una diferencia de conjuntos sobre ids, que `Plan` expone como una colección de `Record`s. Que sea de `Record`s y no de `Step`s no es un detalle: un `Step` lleva un artefacto, y un retiro se define justamente por que el render no produjo ninguno; lo único que queda de él es lo que el journal todavía recuerda. El núcleo ya admitía esa asimetría en otro lado: `Retired` es un tipo aparte de `Applied` por la misma razón.

La regla vive en el núcleo y no en `cli.py` porque `tui/` es el segundo adapter conductor, y el punto de un hexágono es que todos obtengan la misma respuesta del núcleo: duplicar una regla del contrato de propiedad hace que la CLI y la TUI diverjan en el criterio, no en el número. Cuando una release deja de embarcar una skill, un comando o un agente, esto lo retira; dejar de nombrar un servidor MCP es un caso más.

Dos cosas quedaron atadas al retiro y no son negociables. El snapshot cubre las direcciones retiradas —la ruta de un retiro nunca cae en `plan.placements`, así que sin nombrarla el `restore` devolvería la clave de un servidor y no su archivo de convención—; y el journal descarta **lo que `retire` confirmó haber removido**, nunca lo que se pretendía remover, porque una entrada que quedó `unaccounted` sigue en disco y perder su registro la orfanaría para siempre.

#### Lo que el dry-run no puede prometer

`--dry-run` anuncia los retiros, y para un artefacto con dirección propia lo que anuncia es lo que va a pasar. Para un ítem agregado a una lista —puntero terminado en `/-`— puede quedarse corto: si el usuario lo editó más allá de reconocerlo, la corrida real lo va a dejar `unaccounted` en vez de removerlo, y el dry-run no tiene cómo saberlo.

No es un defecto a arreglar, es el precio de dos decisiones deliberadas: `retirements()` es pura y no mira disco, y el dry-run no llama a `retire`. Comprar la precisión exigiría romper las dos.

### Instalar y desinstalar pisan, el snapshot recupera

El digest no es permiso. La política son tres reglas:

- **Instalar** escribe todo lo que el journal reclama, sin mirar si el usuario lo tocó. Lo que el journal no reclama —una dirección ocupada por algo ajeno— es una colisión y se saltea.
- **Desinstalar** borra todo lo que el journal reclama, sin mirar si el usuario lo tocó.
- **Recuperar** es el snapshot y `restore`. No el journal.

La única pregunta que decide si se escribe es «¿esto es nuestro?», y la contesta el journal solo. Conviene decir qué NO justifica el snapshot: una dirección que el journal no reclama ya está protegida (se saltea), y una instalación que se corta a mitad de camino ya está protegida por el rollback en memoria del planner (`Applied.replaced` y `_put_back`), que deshace lo que un solo comando alcanzó a tocar mientras corre.

El hueco real es uno solo: **una dirección que el journal sí reclama, donde el usuario editó a mano el archivo que es nuestro.** Ahí la política escribe sin preguntar, así que no hay consentimiento y no hay aviso. El snapshot existe para que ese contenido no desaparezca sin dejar rastro. El precio se dice en voz alta: si pasaron más instalaciones que las que la retención guarda, el contenido original no existe en ningún lado.

`unaccounted` existe porque un ítem de una lista no tiene dirección propia, así que «el usuario lo borró» y «el usuario lo editó hasta volverlo irreconocible» son físicamente indistinguibles, y esto sólo aplica a listas que todavía tienen sobrevivientes. El digest sigue siendo el identificador de esos ítems y un dato de `doctor`; `ownership.occupies` detecta una dirección ocupada por algo ajeno; y `Capability.PER_AGENT_MODEL` está clasificada `INTERACTIVE` en `catalog.py`.

#### Asignación de modelo

> Una asignación de modelo no es una mutación de nuestro artefacto. Es una preferencia que vive en el estado propio de HPL y participa del render.

Pisar el artefacto es inofensivo, porque la asignación no vive en el artefacto: es parte de lo que renderizamos, no algo que haya que proteger de nuestra propia escritura. La preferencia vive en su propio store (`model_assignment_store_file.py`), con su propio puerto, al lado del journal pero con una postura de falla opuesta: **falla blando**. Ausente o ilegible degrada a «sin asignación» y se renderiza el default, deliberadamente al revés que el journal, que revienta ante un archivo corrupto porque degradar ahí orfanaría artefactos propios.

#### El snapshot — el contrato de diseño

El snapshot captura el archivo entero, siempre. Un blob por archivo tocado, sin importar si HPL iba a escribir el archivo completo o sólo una clave adentro. `restore` devuelve bytes exactos y modo exacto, sin merge ni reconstrucción — el modo importa porque `_write_document`, en `planner.py`, ya escribe un documento de configuración con el modo que el archivo tenía antes, y devolverlo como `0644` rompería algo que el motor ya respeta hoy.

El snapshot captura también el journal. El journal no está en `plan.placements` —lo guarda el store propio, no el planner—, así que hay que agregarlo a mano a lo que se captura. Si no, `restore` devuelve los archivos al estado anterior mientras el journal sigue reclamando la versión nueva, y la próxima instalación compara contra las huellas equivocadas.

Es una carpeta por generación, numerada con un número creciente, colgando del mismo directorio donde vive el journal:

```
~/.local/share/hpl/snapshots/
  000004/
    manifest.json
    0001.blob
```

El manifest se escribe último, como marca de que la generación está completa. Una carpeta sin manifest la ignoran tanto `restore` como la retención. Cada entrada del manifest tiene la ruta, `existed`, el modo, y la referencia al blob. `existed: false` significa que ahí no había archivo, así que volver a ese estado es borrar la ruta — eso es lo que permite que `restore` devuelva el estado anterior exacto y no simplemente sobrescriba.

La fecha va adentro del manifest, no en el nombre de la carpeta. La razón real: en los tests el reloj es un literal fijo (`AT`, en `tests/test_cli.py`), y el test que prueba "hay snapshot en instalar Y en desinstalar" toma exactamente dos snapshots en una misma corrida — con la fecha en el nombre, colisionarían. Una razón secundaria: `timespec="seconds"` no da orden total, y la retención necesita ordenar. No vale el argumento de que en producción dos snapshots en el mismo segundo son improbables — ese argumento se consideró y se descartó.

`restore` deshace la instalación completa, no un rescate selectivo archivo por archivo. Devuelve todo lo que la instalación tocó, y hay que decirlo sin vueltas: eso significa que también se vuelve a la versión anterior de todo lo demás que esa instalación actualizó, no sólo del archivo que motivó la recuperación.

La retención guarda 20 generaciones, y no es un argumento de disco: el contenido son 100 archivos y 448 KB (`find src/hpl/content -type f`), el catálogo de OpenCode sin MCP renderiza 97 archivos y 22 claves de configuración (entradas del journal por tipo, tras una instalación real en un HOME descartable), así que un snapshot de reinstalación son unos 450 KB y veinte generaciones son unos 9 MB -- medido en una máquina real, cinco generaciones ocupan 436 KB en total (64-144 KB cada una), muy por debajo de esa cota superior, porque una instalación real toca menos archivos que el peor caso de reinstalación completa. Lo que la retención decide en realidad es cuánto atrás llega la promesa de recuperación.

El puerto de filesystem ofrece `list_dir` —para calcular el próximo número de generación y para la retención— y un método para borrar un directorio, que sólo usa la retención. Hace falta porque `remove` es explícitamente sólo para archivos (`ports/filesystem.py`; en `fs_posix.py` es `path.unlink`, que falla contra un directorio). No hay archivos comprimidos en ningún lado de `src/`: los snapshots son archivos sueltos, por diseño.

### El puerto de filesystem puede decir «no puedo saberlo»

Una ruta que existe y no se puede leer no se hace pasar por ausente. `exists` y `list_dir` levantan `FileSystemError` cuando no pueden responder, y `exists` sigue devolviendo un `bool` para presente y ausente. Se eligió contra una alternativa de tres estados porque la propagación ya estaba cableada en el `except` de `main`, y porque `None` es *falsy* en Python: un tercer estado habría reintroducido el defecto, en silencio, en cualquier `if fs.exists(path):` escrito después.

Tragarse el error y devolver `False` parece lo que el contrato pide y destruye datos: un snapshot tomado con un directorio ilegible anotó como ausentes 16 archivos que existían, y el `restore` posterior los borró y reportó éxito. `planner._file_step` ya tiene la guarda contra esa pérdida (un archivo que no se puede leer no se pisa), y un `False` falso la rodearía; `FileJournalStore.load` convertiría un journal ilegible en uno vacío y todo seguiría como si HPL nunca hubiera instalado nada.

La clasificación de los sitios que llaman a `exists` por lo que causaría un `False` que significa «no puedo saberlo»:

| Consecuencia | Sitios |
|---|---|
| **Destructiva** — se pierden datos | `planner._file_step` (planificaría `CREATE` sobre un archivo que existe, y `apply` lo pisa); `planner._read_document`; `FileJournalStore.load`; `capture_paths` |
| **Deshonesta** — un reporte o el journal afirma algo falso | `retire` (saltearía el borrado y apilaría el id en `removed`); `_current_digest` (`doctor` reportaría como ausente algo presente); `readable_generations` (un `restore` sin argumento elegiría una generación más vieja); y los `left`/`existing` de `_install` |
| **Benigna** — degrada sin daño | `FileSnapshotStore.read` (rechaza igual, con el motivo equivocado); `list_dir` |

Tres sitios necesitan algo más que la propagación: `doctor` tiene un tercer balde (una entrada que un permiso tapa no está ausente ni derivada); `readable_generations` es un bucle explícito, porque una generación vieja ilegible no debe impedir encontrar la más nueva y buena; y las consultas de `left_behind`, que corren adentro de un handler que ya está reportando otra falla, no reemplazan ese mensaje específico por el genérico. Los tests de estos casos corren contra un home descartable con el filesystem real y atan la falla de consulta al **estado del disco** y no a un contador de llamadas, que codifica cuántas veces el motor pregunta hoy.

`owned_by_current_user` falla seguro: un «no puedo saberlo» da `False` y el guard se niega a escribir. `mode_of` distingue en el puerto «la ruta no existe» de «no pude leer sus bits», y `_write_back` omite el modo en vez de elegir un default que no le toca. Los permisos no son un octal en el núcleo: `FileArtifact` dice `executable`, los bits nacen en `mode_for` del lado de la plataforma, un solo guard `writable_on_behalf_of_owner` lo usan los tres stores, y un test guardián sostiene que ningún literal de permiso vuelve a `core/` ni `ports/`.

---

## Contrato de los MCP, permisos y reportes

### El contrato de un MCP tiene dos mitades, y las dos responden a la misma elección

Un MCP tiene dos mitades. La primera es **la convención**, que es el cuerpo del descriptor y viaja a `_shared/mcp/<id>-convention.md` sólo si el servidor se selecciona. Es el detalle operativo —orden de herramientas, presupuesto, formatos— y se lee a demanda.

La segunda es la que hace que la primera se lea alguna vez: **la referencia fuerte**. Qué es el servidor, qué puede hacer el agente con él, y el puntero a la convención. Se paga en cada turno, así que es corta a propósito.

Vive en `content/agents/mcp/<id>.md`, y `content/agents/mcp/<id>@<agente>.md` la reemplaza para un agente cuyo encuadre lo justifique — el orquestador dice que el descubrimiento estructural en profundidad **no** es suyo, y `king-hpl` dice lo contrario porque actúa en vez de delegar. El prompt de sistema tiene su propia versión del mismo mecanismo en `content/system-prompt/mcp/<id>.md`.

Cada agente resuelve sus secciones desde su propio `optional_mcp`, que es exactamente la lista que `select_mcp` ya poda. Eso es lo que hace que **un grant y la instrucción que le dice al agente que lo use no puedan discrepar**: salen de la misma fuente.


### Un servidor se puede atar a uno que la persona ya administra

`--mcp ID=CLAVE` le dice a HPL que lo que él llama `cbm` es un servidor que la instalación ya corre bajo otra clave. Concede sus herramientas y embarca su convención; **no obtiene el binario, no escribe la entrada de configuración, no toca la versión**. Existe porque la alternativa era peor: instalar el servidor de HPL al lado del que la persona administra deja dos versiones sobre un mismo store.

La clave se valida donde todavía es algo que alguien tipeó. Se empalma textual en reglas de permiso de los dos lados del grant, y el runtime lee `*` y `?` dentro del nombre de una regla como patrón: una clave con comodín renderiza una regla que le gana al deny baseline para todo. Una regla no se distingue de una que alguien quiso una vez que está en el mapa.

### Un servidor que la persona administra, sin descriptor ni convención, se concede a todos los agentes por igual

`--mcp ID=CLAVE` es para un servidor que HPL conoce: tiene descriptor, y por lo tanto convención y referencia fuerte. Falta el caso de uno que HPL nunca vio -- Jira, Figma, cualquier MCP que la persona instaló y administra por su cuenta. Para ese caso no hay descriptor donde declararlo: un `reaches` exigiría un descriptor y una convención que no existen, y forzarlo a esa forma haría que `_require_mcp_convention_referenced` se niegue con razón, porque ningún cuerpo de agente referencia jamás un servidor del que nadie escribió una línea.

`Install.granted_mcp` y `Agent.granted_mcp` son el campo aparte que resuelve esto: `hpl mcp grant --cli <id> <clave>` la agrega, y `content.grant_mcp` la aplica **igual a todos los agentes**, nunca por agente -- la decisión explícita fue que agregar un MCP más no debía volverse una tarea tediosa de tocar archivo por archivo. El render escribe `<clave>*` en `tools` y `permission`, exactamente como el comodín de un servidor propio, pero después del comodín de `optional_mcp` y antes de `denied_mcp_tools`: si un servidor propio de HPL ya negó una herramienta puntual a un agente, un grant del usuario nunca puede reabrirla.

Se rechaza una clave que coincide con un id que HPL ya embarca, o con una que ya está atada: conceder ahí de nuevo, a todos los agentes por igual, borraría el recorte por agente que esa atadura ya tenía. `mcp grant` además se niega a otorgar una clave que la configuración propia de la CLI no declara -- la misma lógica de `_require_mcp_convention_referenced`, aplicada donde no hay convención que verificar: un error de tipeo no debe traducirse en un permiso que nadie nota que falta.

### El comodín de un servidor no alcanza lo que destruye

Conceder las herramientas de un servidor se hace con `<clave>*`, y esa granularidad es correcta: un descriptor no debería enumerar todo lo que un servidor expone. `withheld_tools` nombra, **por excepción**, lo que ese comodín no debe alcanzar, y el render lo escribe después del grant, que es lo único que lo hace ganar.

Lo que se retiene se decide por lo que destruye estado, no por lo que parece peligroso: `index_repository` **no** se retiene, porque la convención de CBM lo prescribe como la reparación de un índice viejo, y denegarlo rompería una regla que el producto mismo le da a sus agentes.

### Leer fuera del worktree es un permiso propio

El runtime pregunta por `external_directory` antes que por `read` cuando el destino queda fuera del árbol del proyecto, y los nombres de permiso se matchean por comodín. Todo el contrato de lazy-loading vive bajo el directorio de skills, que está fuera de todo worktree.

El mapa `external_directory` de un agente se escribe en este orden, y el orden es lo único que decide qué gana, porque el runtime resuelve por la última coincidencia: la línea de base `"*": "allow"`, la excepción acotada al directorio de skills (y no al de configuración que lo contiene: ahí vive el archivo de settings), los directorios que la persona otorgó y, al final, un piso de denegación fijo. La línea de base es la misma para todo agente, primario o sub-agente, y es una decisión de producto y no un parche a la espera de un arreglo río arriba; su costo y su motivo están en «Limitaciones aceptadas».

La clave sólo la traen las herramientas cuyo equivalente en el runtime efectivamente pregunta bajo ese nombre (`read`, `grep`, `glob`, `edit`, `write` y `bash`, ver `EXTERNAL_DIRECTORY_TOOLS` en `render.py`; `bash` no llama `assertExternalDirectory` como las otras cinco sino que pide el mismo permiso por su cuenta), de modo que un agente que declare `edit`, `write` o `bash` sin `read` también la recibe.

### Un directorio de trabajo propio es un dato que la persona declara, no una excepción que se edita a mano

La sección anterior resuelve la ruta de skills, fija y conocida en tiempo de release. Un directorio de trabajo que un agente necesita -- un worktree enlazado, un árbol de scratch fuera del proyecto -- es un hecho que HPL no puede conocer de antemano, y no hay forma soportada de declararlo: HPL reclama la entrada completa de cada agente en la configuración renderizada, así que una excepción agregada a mano la pisa el siguiente `install`/`update`.

`Install.granted_directories` y `Agent.granted_directories` siguen el mismo molde que `Install.granted_mcp` ya estableció para el problema gemelo: `hpl directory grant --cli <id> <ruta>` la agrega, sobrevive a cada reinstalación, y `directory revoke` la quita. A diferencia de un grant de MCP, no hay colisión que rechazar -- un directorio no comparte espacio de nombres con nada que HPL ya renderice por agente -- así que `content.grant_directories` no tiene la lógica de `droppable` que `grant_mcp` necesita, y alcanza a todo agente por igual, sub-agentes incluidos: una necesidad de directorio propio en un sub-agente es exactamente el caso que este mecanismo existe para resolver.

La validación rechaza lo que no puede ser una ruta segura: relativa, con `..`, cualquier metacarácter de glob que el propio matcher del runtime interpreta (`*`, `?`, y también `[`/`]` por precaución -- una ruta que llega verbatim a una regla de permisos es exactamente el lugar donde conviene rechazar de más), o la raíz del filesystem -- conceder `/` renderizaría `/*`, y como el comodín del runtime cruza `/`, esa regla coincide con cualquier ruta absoluta que exista, un segundo baseline abierto de par en par con el valor contrario al que se quería escribir. También se rechaza el directorio de configuración de la CLI y cualquier ruta que sea su ancestro: ese directorio contiene el archivo de settings con lo que la persona haya configurado de sus propios servidores, y este producto ya decidió conceder sólo el subárbol de skills debajo de él, a propósito -- una ruta ancestro reabriría esa puerta por otro lado. Por el mismo motivo se rechaza también el directorio de datos del propio HPL (donde vive el journal): darle `write` a todo agente sobre ese directorio convertiría una escritura cualquiera en un borrado arbitrario en la próxima `uninstall`, que lee ese journal sin volver a validarlo contra el disco. Ningún otro directorio de la máquina se cierra de esta forma -- estos dos se cierran porque el propio HPL depende de que sigan intactos, no porque sean sensibles en abstracto. Deliberadamente **no** se valida contra el home de la persona, a diferencia de cada otra ruta que este código guarda: un directorio de trabajo legítimo puede estar en cualquier parte de la máquina.

La ruta persistida -- en el journal, en lo que reporta `grant`, en lo que compara `revoke` -- es siempre la forma normalizada que devuelve la validación (`Path(...).as_posix()`), nunca la cadena cruda que la persona tipeó: una barra final, un `.` de más o `//` repetidas colapsan a la misma forma, así que otorgar con una grafía y revocar con otra equivalente funciona.

El render escribe cada directorio concedido como `f"{ruta}/*": "allow"` en el mismo mapa `external_directory`, después del baseline y de la excepción de skills -- el orden es lo único que lo hace ganar, la misma regla de resolución que gobierna todo lo demás en ese mapa.

Con la línea de base en `"allow"`, un directorio otorgado no cambia nada observable para una ruta ordinaria: su entrada sigue en el journal y se sigue renderizando, y recuperaría su sentido completo si la línea de base volviera a `"ask"`. Sólo importa cuando solapa el piso de denegación, donde sigue denegado.

### Lo que `doctor` puede y no puede afirmar

`--start-mcp-servers` es la única forma en que `doctor` deja de ser de sólo lectura: lanza cada servidor que el journal reclama y clasifica su handshake. Un servidor **atado** no tiene entrada de configuración que lanzar, así que se reporta con estado `bound`. Una instalación con todos sus servidores atados no dice «No MCP servers configured», que sería una afirmación falsa.

Lo que no se afirma es más de lo que el journal sabe, y son dos cosas: a qué clave se lo ató, que nunca se registró; y que sea con certeza una atadura, porque `retire` recorre los tipos en orden alfabético y un uninstall interrumpido deja la misma forma.

`mcp_granted` es una clave propia, distinta de `mcp_bound`: una clave otorgada no es una atadura -- HPL no le embarca descriptor, no le concede convención, y no la instaló. Confundir las dos bajo un mismo encabezado diría que algo se ató (lo que implica que un contrato viaja con eso) cuando acá nunca se embarcó nada en absoluto.

### El journal alcanza al disco sin escribir

`install` decide "already current" contra el disco; `doctor` reporta drift contra el journal. Una edición a mano que acierte lo que una versión posterior renderiza deja las dos peleadas para siempre: no se escribe nada, el journal no se actualiza, y cada corrida repite la conclusión.

Un paso `unchanged` ya carga las dos mitades de la respuesta, así que el registro que falta no cuesta un acceso a disco. Viaja en `Applied.reconciled` y **no** en `Applied.records`, y esa separación es la corrección entera: `records` es lo que un rollback puede sacar, y una reconciliación es un artefacto que la corrida nunca escribió.

### `hpl --version`

Lo contesta el parser y nada más: no abre un home, no lee un journal, no resuelve un adapter. El número es del binario y no de ninguna instalación suya, y una máquina con la instalación rota es exactamente donde tiene que seguir funcionando. Sólo antes del subcomando, a diferencia de `--json`: `--json` modifica un reporte y va donde va el comando que modifica, y una consulta de versión no modifica nada.

### Un asset que viaja verbatim no puede nombrar la marca

La sustitución de una distribución alcanza `.md` y `.txt`; el cuerpo de un `.py`, un `.ts` o un `.json` viaja tal cual. De ahí sale una regla: **un asset cuyo cuerpo viaja verbatim no puede nombrar la marca del motor**, porque esa marca aparecería literal en una instalación que no se llama así.

El guardián recorre **todo** lo que no sea `.md` ni `.txt` bajo `adapters/*/assets/`, deriva el conjunto del árbol y la marca de `identity.json`, y acepta el placeholder mientras rechaza el literal: `{{program_name}}` es la forma correcta de nombrar al producto. Lo que no se deriva se declara con su razón (por ejemplo un identificador de esquema como `hpl-registry-assets/v3`, de la misma familia que los `SCHEMA` de `core/journal.py` y `core/catalog.py`, que se queda literal), y la lista de excepciones tiene su propio guardián que exige que cada entrada siga nombrando un archivo real. Las excepciones se aprueban por ruta y no por nombre de archivo: aprobar por un proxy en vez de por el hecho dejaría exento gratis a cualquier archivo nuevo llamado igual.

### Enmendar el texto del runtime, no sólo agregar el propio

Los plugins que este producto embarca agregan comportamiento suyo: un registro de skills, un notificador, un reporte de estado. Uno solo toca lo que el runtime le dice al modelo, y conviene declararlo como línea aparte, con su motivo y su límite.

El motivo es un caso real. El runtime pliega `edit`, `write` y `apply_patch` sobre un único permiso `edit` para decidir qué herramientas manda, y el comodín del mapa `tools` renderizado no lo alcanza porque ese filtro compara por clave exacta. Conceder `edit` entrega `apply_patch`, y **no hay forma de negarla** sin negar la edición entera. Su descripción abre con un imperativo —«Use the `apply_patch` tool to edit files»— y un modelo lo trató como instrucción de prioridad de desarrollador que supera al prompt de sistema: se negó a editar un archivo en otro host por SSH aunque la persona lo autorizara explícitamente, y siguió negándose después de que el prompt compartido dijera lo contrario. Su propia explicación fue la que señaló la salida: lo que lo obliga es el texto que llega **con las definiciones de herramientas**, no el que llega como prompt.

`tool.definition` es el único gancho que escribe en ese mismo canal. Se dispara donde se arma la descripción que viaja al modelo, y lo que el plugin deja en `output.description` es lo que efectivamente se manda.

**El límite, que es la parte que importa:** esto se usa cuando el texto del runtime contradice lo que el producto necesita **y no existe palanca de permisos**. No es una licencia para reescribir a gusto lo que el runtime dice. Un permiso que se puede denegar se deniega; una herramienta que se puede no conceder no se concede; recién cuando las dos están cerradas —como acá, donde la herramienta viaja atada a un permiso que sí queremos— se enmienda el texto.

Y se **agrega**, no se reemplaza. Cortar la frase imperativa exigiría acertarle a un texto del runtime que puede cambiar: el día que lo reescriban, el reemplazo dejaría de aplicar **en silencio** y parecería que el defecto volvió. Un agregado sigue siendo cierto diga lo que diga el resto de la descripción.

Hexagonalmente no hay nada nuevo: un plugin es un artefacto del runtime y vive donde ya vivían los otros, en `adapters/opencode/assets/plugins/`. El core no sabe que existe, y otro CLI traerá los suyos o ninguno. Lo que sí es nuevo es que una distribución hereda esta postura junto con el motor, sin decidirla por su cuenta.

Una trampa propia de este formato: el rebrandeo de una distribución sustituye sólo `.md` y `.txt`, así que el cuerpo de un `.ts` viaja tal cual. El nombre del archivo sí se deriva de la identidad; el texto de adentro no puede nombrar la marca del motor, o una distribución embarcaría un plugin que se presenta con el nombre equivocado.

## Identidad de producto y raíz de composición

El nombre, el wordmark, el directorio de datos y la fuente de auto-actualización no están escritos como literales en `cli.py`, `core/upgrade.py` ni `tui/wordmark.py`: cualquier organización puede producir su propia distribución del motor sin bifurcar la fuente.


**La identidad es un dato, nunca una rama de código.** `src/hpl/identity.json` declara
`product_id`, `display_name`, `program_name`, `wordmark_words` y un bloque `release` (plantilla de
URL del asset, nombre del binario, API de último release, página de releases). `core/identity.py`
lo parsea una sola vez — `parse()` valida charset y longitud de cada palabra del wordmark (sólo
`A-Z`/`0-9`, hasta `MAX_WORD_LENGTH` caracteres), que cada URL de `release` sea `https` con host
real (contra `urlsplit`, no un prefijo, para que `https://github.com@evil.example.com` no pase por
`github.com`), y que `binary_asset` no tenga separador de ruta ni `..`. Nunca hay un valor por
default: si `identity.json` falta o no valida, el arranque falla con `IdentityError` antes de que
cualquier comando corra.

**La versión también es un dato de identidad, obligatorio, nunca la del motor.** `identity.json`
declara su propio `version`, validado en `parse()` con el mismo charset (`SAFE_VERSION`) que
`core/upgrade.py` ya usaba para sanear el `tag_name` de un release remoto antes de construir la URL
de descarga — una sola regla, no dos que puedan divergir. No hay default a `hpl.__version__`:
una distribución fija este motor en una versión y publica sus propios releases con una numeración
completamente distinta, así que `--version`, la comparación de `upgrade` (`already-current`) y el
valor de `hpl_version` en `doctor --json` leen todos `identity.version`, nunca la constante del
motor — de lo contrario `--version` muestra la versión equivocada y `upgrade` nunca puede detectar
que ya está actualizado. Para el propio `identity.json` de HPL, un test de versión mantiene
`pyproject.toml`, `hpl.__version__` e `identity.version` iguales entre sí; esa igualdad de tres
vías es una propiedad sólo de la distribución propia de HPL, nunca una regla general.

**La raíz de composición es `cli.py`.** `default_identity()` lee el `identity.json` empaquetado
(vía `importlib.resources`, igual que `core/content.py` lee `content/`) y arma el único `Identity`
congelado de la corrida; `default_runtime` lo cuelga de `Runtime.identity` y lo cablea a `argparse`
(`prog=`, `description=`, `help=`), a los mensajes de `install`/`upgrade`/`uninstall`, y a
`core/upgrade.py` como el `ReleaseSource` contra el que se auto-actualiza. `core/`, `ports/`,
`infra/` y `tui/` nunca conocen el nombre de una distribución: lo reciben como parámetro. Un test de
arquitectura (`NoProductIdentityOutsideCompositionRootTest`) recorre el AST de esos cuatro paquetes
buscando literales de string que mencionen un nombre de distribución conocido — no un `grep`, porque
la palabra "HPL" aparece legítimamente en decenas de docstrings y comentarios; sólo un literal
que no sea docstring cuenta como ofensor, con una lista explícita de excepciones para los
identificadores de wire format que nunca cambian entre distribuciones (`cli.SCHEMA`,
`journal-v4.json`, las claves `hpl_version`/`hpl_installed`, etc. — ver más abajo).

**El nombre del orquestador también es un dato de contenido, no del motor.** `content/session-start.txt` declara qué agente abre la sesión (`core/content.py: SESSION_STARTS_IN`), así que una distribución que renombra su orquestador lo hace en `content/`, sin tocar `core/`. El adapter de OpenCode (`adapters/opencode/render.py`) no repite ese nombre como literal: `render.command` recibe el nombre del orquestador como parámetro obligatorio, leído del `Content` cargado, y el scan de `NoProductIdentityOutsideCompositionRootTest` también recorre `adapters/` (en un tuple propio, separado del que usa `NoCliNamesOutsideAdaptersTest`, porque ese paquete legítimamente sí conoce qué CLI es, sólo no qué distribución es).

**El wordmark se dibuja, no se elige.** `tui/wordmark.py` cubre el mismo alfabeto que
`core.identity.ALLOWED_CHARACTERS` (`A-Z` y `0-9`), verificado por un test que compara los dos
conjuntos en las dos direcciones; el renderer dibuja la cantidad de palabras que `identity` le da
(una o dos), sin ninguna rama sobre el conteo.

**`tools/build_zipapp.py --identity` es obligatorio, siempre — incluso para el propio release de
HPL.** Es la única forma en que "una distribución no puede olvidarse de dar su propia identidad"
sea una propiedad real y no una convención: sin el flag, `argparse` rechaza la construcción antes de
escribir un solo byte. El nombre se valida con las mismas reglas de `core/identity.py` — cargado
como módulo standalone desde el propio `--source` que se está construyendo, nunca importado del
motor que corre la build, para que la regla de validación nunca pueda divergir de la que corre el
binario resultante.

**`install.sh` también se genera por identidad, con `tools/build_installer.py`.** El instalador
shell es la última pieza de la distribución que seguía hardcodeada: vive en la raíz del repositorio
como una plantilla, con un único bloque de identidad delimitado por dos líneas `# ====...====` cerca
del principio del archivo -- la raíz de composición del lado shell, el equivalente de `cli.py` del
lado Python. `tools/build_installer.py --identity <identity.json> --out <ruta>` reemplaza sólo esas
cuatro líneas (`PRODUCT_ID`, `PRODUCT_DISPLAY_NAME`, `PRODUCT_PROGRAM_NAME`,
`PRODUCT_RELEASE_BASE_URL_DEFAULT`) por los valores de un `identity.json`, carácter por carácter
igual en el resto del archivo, y valida ese `identity.json` cargando `core/identity.py::parse()`
igual que `build_zipapp.py`. Un test, análogo en espíritu a
`NoProductIdentityOutsideCompositionRootTest` pero para shell en vez de Python, escanea todo
`install.sh` fuera de ese bloque buscando el nombre de una distribución conocida.

**Lo que nunca varía por distribución** son los identificadores de wire format que otro programa
parsea: `cli.SCHEMA`, `journal.SCHEMA`, `catalog.SCHEMA`, el nombre de archivo `journal-v4.json`,
las claves JSON `hpl_version`/`hpl_installed`, y las variables de entorno
`HPL_SKILL_REGISTRY_BIN`/`HPL_SKILL_ROOTS`/`HPL_NO_UPDATE_CHECK`. Cambiarlos rompería a
cualquier programa externo que ya los interpreta; la identidad de producto vive en una capa
completamente distinta de la de esos contratos.

**No-objetivo, deliberado: un producto por usuario del sistema operativo.** Instalar dos
distribuciones bajo el mismo usuario no corrompe el journal ni el directorio de datos de ninguna de
las dos — cada una está separada por su propio `product_id`. Pero `~/.config/opencode` y su
`opencode.json` siguen siendo un recurso genuinamente compartido del cliente anfitrión, no de
HPL, y este cambio no los vuelve seguros para dos productos a la vez: la segunda instalación
sobreescribe lo que la primera dejó en esa configuración compartida. Esto se documenta como
comportamiento conocido, no se soluciona acá — convivencia de dos productos bajo el mismo usuario no
funciona, y no hay que dar a entender lo contrario.

## FTD y la escalera de rutas

HPL conoce cuatro maneras de trabajar: la consulta, el cambio directo (L0), **FTD — Fast-Track Development**, y SDD. FTD es un cambio gobernado liviano, con un record durable en el proyecto y sin la cadena de fases; SDD tiene preflight, artifacts, fases y `sdd-verify`. Esta sección fija cómo se elige la ruta y cómo se recorre cada una.

### El problema y las dos reglas

La tesis cabe en una línea:

> **"No merece SDD" no equivale a "no merece ningún estado durable".**

Un pedido que no es SDD no termina sólo en una respuesta o en un diff: si el cambio necesita un checklist, sobrevivir a una compactación o dejar evidencia agrupada, FTD es donde ponerlo. **FTD es el carril habitual del trabajo ordinario**, aunque la superficie sea grande, y SDD queda para lo que necesita un contrato revisable antes del código. FTD no es un SDD reducido: no usa `sdd-apply` ni `sdd-verify` fuera de sus contratos.


Dos reglas gobiernan el diseño, como las dos del principio de este documento gobiernan el motor:

> **1. Decidir y ejecutar son capas distintas.**

Un archivo decide qué ruta toma un pedido; otro enseña a recorrer la ruta elegida. Ninguna frontera entre rutas tiene dos dueños, y nadie carga el procedimiento de una ruta que no va a recorrer.

> **2. El router no debe convertirse en el manual de todos los flujos.**

El cuerpo always-on del orquestador lleva sólo las pistas para saber si hace falta clasificar; la clasificación vive en un archivo que se lee cuando la ruta no es obvia, y el cómo de cada ruta en otro que se lee al recorrerla. La prueba para saber dónde va un párrafo: **¿hace falta para elegir la ruta, o sólo para recorrerla?** Lo segundo nunca va al router.

### Por qué `needs_reviewable_contract` y no `needs_agreement`

Un fact que preguntara sólo si hay una decisión que tomar mandaría casi todo a SDD: casi cualquier cambio real tiene una. Lo que separa a SDD del resto no es que haya una decisión sino que la decisión tiene que poder revisarla, antes del código, alguien que no va a ver la implementación, o que otros van a construir contra una spec sin estar en el cambio. Cuando quien decide ve aterrizar el código en el mismo documento vivo, y puede corregirlo, el documento cumple la función de la propuesta. Una decisión o un trade-off sin contrato revisable no cambia la ruta: se toma, se registra en *Decisions* del record FTD y se sigue. Una decisión que tiene que sobrevivir a la sesión cuenta como `needs_continuity`, así que va a FTD y no a L0. Y **la coordinación entre sesiones no dispara SDD**: es continuidad, y la resuelven el record FTD, el documento vivo del proyecto y Engram.

Las reglas de evidencia de FTD salen de fallas de instrumento reales: mediciones y checks que informaron éxito, o una cifra, y eran falsos. Están en [Reglas de evidencia de FTD](#reglas-de-evidencia-de-ftd).

### Las cuatro rutas y los routing facts

La separación obligatoria es de cuatro rutas. Las preguntas son semánticas, no una tabla de umbrales:

| Ruta | Pregunta representativa | Qué NO la decide |
|---|---|---|
| Consulta / observación | ¿El resultado buscado es información, una recomendación, una investigación o un check, sin modificar todavía el sistema? | Que el tema sea grande, urgente o afecte muchos archivos |
| L0 — cambio directo | ¿Hay una única intervención ya comprendida, sin decisión pendiente, que puede ejecutarse y demostrarse con evidencia puntual? | La cantidad de archivos, líneas, comandos o entidades afectadas |
| FTD | ¿El cambio puede cerrarse y ejecutarse sin un acuerdo formal de diseño, pero necesita continuidad, alcance explícito, checklist y evidencia durable? | La falta inicial de detalle: se investiga y se pregunta para cerrar el alcance antes de aplicar |
| SDD formal | ¿Hay que fijar, antes del código, un contrato o una decisión que tiene que poder revisar alguien que no va a estar en la implementación, o una spec contra la que otros van a construir? | Que haya una decisión o un trade-off que resolver, el tamaño del diff o el miedo a equivocarse |

Las respuestas se reducen a **cuatro routing facts**, que son a la vez el contrato entre `hpl-explorer` y el orquestador y el vocabulario del corpus de tests:

| Fact | Pregunta |
|---|---|
| `output_is_information` | ¿El resultado buscado es información, recomendación, investigación o un check? |
| `asked_for_sdd` | ¿Pidió SDD, spec o plan explícitamente, por comando o con sus palabras? |
| `needs_reviewable_contract` | ¿Hay que fijar antes del código un contrato o una decisión que tiene que poder revisar alguien que no va a estar en la implementación, o una spec contra la que otros van a construir? |
| `needs_continuity` | ¿Necesita continuidad, checklist, handoff o evidencia durable? |

Lo único fijo es el orden en que se consultan:

1. `output_is_information` → **consulta**.
2. `asked_for_sdd` → **SDD**; el pedido explícito es la aceptación.
3. `needs_reviewable_contract` → **se propone SDD**, y se entra sólo con aceptación explícita.
4. `needs_continuity` → **FTD**.
5. Ninguna de las anteriores → **L0**.

> **El tamaño nunca es un fact.**

Ni la cantidad de archivos, ni las líneas, ni la urgencia: nada del routing puede depender de ellos. Un cambio distribuido en muchos archivos sigue siendo L0 si es una única operación trivial, atómica y demostrable; uno de dos líneas es SDD si fija un contrato que consumen otros. La cantidad de archivos puede ser pista para decidir si conviene delegar, nunca para elegir la ruta.

**Nombres, y la consulta sin número.** Los niveles se llaman L0, FTD y SDD. La consulta no lleva número ni etiqueta propia: alcanza con nombrarla en el orden de `flow-applicability.md`, porque hoy nada la identifica y nada lo necesita. **FTD se activa sólo por routing**: `src/hpl/content/commands/` no tiene infraestructura de comandos para rutas fuera de SDD, y un comando puede sumarse después sin tocar el contrato de facts.

Cuándo entra cada ruta, en corto:

- **Consulta**, cuando el output pedido termina el trabajo: explicar, comparar, investigar, auditar, revisar, correr un check o proponer sin autorización para implementar. No autoriza modificaciones ni crea artifact durable.
- **L0**, cuando, con el alcance cerrado, el cambio es trivial, atómico, mecánico y conocido, sin checklist durable, sin handoff y sin decisión que resolver. Deja un diff, evidencia puntual proporcional y un reporte honesto. **No crea record FTD ni carga el procedimiento FTD.**
- **FTD**, cuando hay intención de aplicar un cambio ya suficientemente decidido, `needs_reviewable_contract` es falso, no hacen falta varias fases ordenadas y el cambio sí merece continuidad, checklist, evidencia durable o handoff. La investigación no espera una autorización literal: investiga, pregunta para cerrar el alcance y, con una propuesta ejecutable, pide una única confirmación antes de escribir —*"Está todo definido y el alcance es X; ¿le doy?"*—. Un upgrade de dependencia con fallout conocido, una migración mecánica grande, un bug con causa confirmada, un renombre transversal o un refactor de varios módulos con el enfoque ya definido son FTD, aunque no sean chicos.
- **SDD**, cuando hay un contrato o una decisión que alguien ausente de la implementación tiene que revisar antes del código; una spec o un plan contra el que otros van a construir; una API, una autorización o un modelo de datos compartido con consumidores que no participan del cambio; varias unidades ordenadas que otros van a ejecutar; o un pedido explícito. Adentro sigue todo el flujo actual —preflight, `sdd-init`, explore a tasks, apply, verify y archive—, con delivery strategy, review budget, ChainPR y `sdd-verify` como autoridad final.

Si la ruta no es obvia, el orquestador obtiene sólo los facts que le faltan: investiga inline dentro de su threshold o delega una exploración estrecha a `hpl-explorer`, que devuelve routing facts y no ejecuta un flujo ni crea artifacts. Todo lo que se juntó para decidir —la investigación de la consulta, los findings, la evidencia de un L0— entra como input de la ruta elegida.

### Tres capas: decidir, ejecutar y nada más en el cuerpo

La primera versión del diseño proponía un archivo de applicability por nivel, y se descartó: para cargar el correcto había que saber de antemano a qué nivel se iba, y cada frontera quedaba con dos dueños. La separación es por función, no por nivel:

| Capa | Archivo | Qué contiene | Cuándo se carga |
|---|---|---|---|
| Pistas | El cuerpo de `hpl-orchestrator.md` y el de `king-hpl.md` | ¿Información o intención de cambio?, ¿pidió SDD, spec o plan?, y que el resto requiere clasificar | Siempre, como hoy |
| Decidir | `src/hpl/content/skills/_shared/flow-applicability.md`, renombre de `sdd-applicability.md` | Las preguntas de cada frontera, los cuatro facts, el orden de decisión y las promociones, con lo que el archivo viejo ya tenía de valor —casos ambiguos, crecimiento a mitad de camino, fail-open— generalizado a las cuatro rutas | Sólo cuando la ruta no es obvia |
| Ejecutar | FTD: `src/hpl/content/skills/_shared/ftd-procedure.md`, nuevo. SDD: el preflight y los gates que ya existen. L0: casi nada | El record, las reglas de evidencia y el cierre de FTD | Sólo al recorrer esa ruta |

`ftd-procedure.md` es de la misma familia que `sdd-session-preflight.md` y `sdd-phase-common.md`: los tres dicen cómo se ejecuta algo que otro archivo ya decidió. `flow-applicability.md` pasa a ser el único dueño de la escalera y sus fronteras, y decide sin enseñar a ejecutar. El orquestador lee como mucho un archivo para decidir y uno para ejecutar, y ningún cuerpo always-on incorpora el texto de ninguno de los dos.
Los techos de palabras usan un test de techo y un gemelo que prueba que re-envolver las líneas no lo esquiva (`tests/test_orchestrator_routing.py`): lo tienen el cuerpo del orquestador, el de `king-hpl.md`, `flow-applicability.md` y `ftd-procedure.md`.

### Transiciones entre rutas

| Desde → hacia | Cuándo | Aceptación | Qué se preserva |
|---|---|---|---|
| Consulta → L0, FTD o SDD | La investigación dejó una propuesta ejecutable | Una consulta no autoriza cambios: *"Ya está definido X, con alcance Y; ¿le doy?"*. Hacia SDD, además, la aceptación explícita de siempre | La investigación entra como input de la ruta nueva |
| L0 → FTD | Deja de ser atómico; necesita varias tareas, otra sesión o un handoff; requiere evidencia agrupada; toca más superficie de la prevista; no se prueba con una evidencia puntual; se vuelve mantenimiento repetible; o aparece una decisión que conviene registrar | La confirmación de alcance de FTD | El record se crea desde el estado actual —qué se hizo, con qué evidencia real, qué falta—, sin fingir que FTD existía desde el inicio ni marcar checks que no se observaron |
| L0 → SDD | Aparece un `needs_reviewable_contract`. Una decisión que se toma y se ve aterrizar en el mismo record promueve a FTD, con la decisión en *Decisions* | Explícita, después de nombrar el hecho nuevo y por qué L0 ya no alcanza | Lo previo queda como exploración y evidencia de entrada; preflight y gates rigen desde la promoción |
| FTD → SDD | Aparece un `needs_reviewable_contract` o un pedido expreso de SDD, spec o plan. Dos diseños razonables o un trade-off, solos, no promueven: se deciden, se registran y el FTD sigue | Explícita, antes de entrar al ciclo | El record es input de proposal, spec y design, sin duplicar datos; SDD no se aplica retroactivamente |
| SDD → FTD o L0 | Nunca de forma automática | — | Una cancelación controlada exigiría decisión explícita, preservación honesta del estado, justificación y tests, y no existe |

Si una promoción no es obvia, se re-evalúa con el contexto disponible y, si los sistemas o contratos involucrados no están claros, se delega una exploración estrecha que devuelve routing facts. Se juzga la complejidad de decisiones y de coordinación, nunca la cantidad de archivos. Es la regla de `flow-applicability.md` para el trabajo que crece hasta SDD, que vale también para las promociones hacia FTD.

### Actores y readiness fuera de SDD

HPL no tiene roles de más ni un pipeline fijo de subagentes para L0 ni para FTD. Qué hace cada agente en las rutas fuera de SDD:


| Agente | Rol |
|---|---|
| `hpl-orchestrator` | Enruta, coordina y hace él mismo los chequeos y la investigación acotada que necesita para decidir y preparar delegaciones; no es un delegador puro. Decide la ruta primero y aplica después el `Direct Work Threshold`, `may_delegate_to`, las capacidades del target y las reglas de paralelismo. No hay pipeline fijo de subagentes para L0 ni para FTD: cada handoff se justifica y nada se delega por ceremonia |
| `king-hpl` | **Aplica a todas las rutas salvo SDD.** Como escribe, arma él mismo el record FTD; si un trabajo suyo tiene que pasar a SDD, lo dice y deriva al orquestador, sin correr el ciclo. Su `may_delegate_to: [hpl-general]` no cambia |
| `hpl-implementer` | El gemelo operativo de `sdd-apply` fuera de SDD: ejecuta L0 y FTD sin heredar preflight, artifacts ni gates exclusivos de SDD |
| `hpl-verifier` | Sigue devolviendo sólo evidencia, nunca un veredicto de readiness |
| `hpl-general` | El worker sin identidad de fase, usable en L0, en la investigación previa y en FTD |
| `hpl-explorer` | Investigación read-only sin artifact de fase; además devuelve routing facts cuando se le piden |
| `sdd-apply`, `sdd-verify` | Sin cambio: `sdd-apply` implementa tareas SDD y `sdd-verify` sigue siendo la única autoridad de readiness SDD |

**Readiness fuera de SDD: la opción (a).** El readiness de L0 y FTD lo declara quien pidió el trabajo —el orquestador, o `king-hpl` en su propia sesión— leyendo la evidencia, que es lo que el verifier ya dice de sí mismo: *"leave the conclusion to whoever asked for it"* . En FTD se ve en el record: un ítem está hecho sólo si tiene asociada una observación concreta. `hpl-implementer` y `hpl-general` pueden llamar a `hpl-verifier` , y justamente por eso el verifier no firma:

> **Nadie que un escritor pueda alcanzar tiene autoridad para firmar.**

**Cuando quien firma también escribió** —un L0 inline del orquestador, o todo lo de `king-hpl`—, nadie declara "listo" sin una observación registrada, y quien firma algo que escribió lo dice explícitamente en vez de presentarlo como verificación independiente. Es la extensión de *"Close the loop you open"* de `king-hpl.md`.

### El record FTD y dónde vive

**Ubicación: `docs/ftd/<YYYY-MM-DD>-<slug>.md` en el proyecto.** El subdirectorio propio evita pisar la documentación que el proyecto ya tenga en `docs/`. Se escribe sin preguntar nada y **se versiona con Git por defecto**. El FTD que crea `docs/ftd/` avisa una sola vez dónde quedó el record y que, si no se quiere subir, se puede excluir con `.gitignore` o con `.git/info/exclude`, que no se versiona. Detectar el primero no necesita estado guardado: es el que crea el directorio.

**Engram es el nexo, no una segunda copia.** Con Engram disponible, las decisiones, el resultado y la ruta exacta del record se guardan también ahí con el protocolo normal (`mem_save`, el resumen de sesión); es lo que permite recuperar el contexto y enlazar un FTD con una promoción posterior a SDD. Sin Engram, el record es la fuente durable y la conversación informa su ruta explícitamente. FTD no crea wiki, no compite con OpenSpec y no crea una tercera memoria; SDD conserva sin cambios su elección explícita de `openspec`, `engram`, `hybrid` o `none`.

El record tiene seis secciones:

| Sección | Qué lleva |
|---|---|
| *Intent* | Lo que el cambio quiere lograr |
| *Scope* | El alcance confirmado antes de escribir —el X del *"¿le doy?"*— |
| *Decisions* | Opcional, sólo si el cambio toma decisiones: una tabla corta de tema, decisión y motivo, como [Decisiones tomadas](#decisiones-tomadas) al principio de este documento. No repite el diff |
| *Checklist* | Los ítems del cambio; uno está hecho sólo con una observación asociada |
| *Evidence* | Los comandos textuales tal como se corrieron, con su exit status y lo que produjeron |
| *Next* | Lo que falta de este cambio, no de todos, con cada ítem en uno de tres estados |

Los tres estados de *Next* son los mismos tres libros que este documento lleva para el trabajo pendiente, y por la misma razón: una deuda que se decidió dejar no es lo mismo que una que espera.

| Estado | Qué lleva |
|---|---|
| Deuda abierta | Lo que la destraba |
| Resuelta | Su evidencia |
| Limitación aceptada | Nada que la destrabe: se decidió que se queda, y se reabre sólo si se reabre la decisión |

Dos reglas más cierran el record:

- **Las decisiones que duran se gradúan.** El record es la bitácora de un cambio: se cierra y no se corrige. Una decisión que sobrevive al cambio —una convención, una limitación aceptada, un invariante— pasa al documento vivo del proyecto, si lo tiene, o a un topic estable de Engram, y el record enlaza hacia allá. Si no hay ninguno de los dos, queda en el record y se dice. Es la diferencia de forma con este documento, que puede corregirse porque es uno solo y se lee antes de volver a escribir; un record por cambio no puede.
- ***Next* enlaza a la cola de trabajo del proyecto**, si existe como topic de Engram, en lugar de duplicarla.

**Sin límite numérico de preguntas.** Se pregunta sólo cuando la respuesta cambia alcance, criterios de aceptación, riesgos, dependencias o evidencia; nunca por ritual.

**Un escritor por vez: el record lo mantiene quien coordina el FTD**, el orquestador o `king-hpl`. Los subagentes devuelven evidencia y él la incorpora.

### Reglas de evidencia de FTD

> **Un checkbox no es evidencia.**

Cada ítem completado se asocia a una observación concreta: test, build, exit status, check de runtime, parseo de configuración, búsqueda confirmada, smoke test o verificación visual apropiada. Un check que no se pudo correr se registra `not-run`, `blocked` o `failed`, nunca como hecho. *Evidence* guarda los comandos textuales con su exit status: además de evidencia, es la materia prima para detectar repetición en el futuro (ver [Fuera de alcance](#fuera-de-alcance)).

Las nueve reglas salen de mediciones o checks que informaron éxito, o una cifra, y eran falsos. Viven en `ftd-procedure.md`, redactadas cortas porque ese archivo se carga en cada FTD:

1. El exit status que importa es el del comando, nunca el de un pipe que lo sigue: `if cmd | tail; then` mide `tail`.
2. Una búsqueda de X no corre donde su propio path contiene X; si no se puede evitar, se verifica antes de creer el resultado.
3. Una cifra que salió con una limitación declarada viaja con esa limitación: "N, con la limitación L" es un solo hecho.
4. Los nombres de artefactos, URLs y archivos que usa un check se derivan de la misma fuente que los produjo, nunca se tipean de memoria.
5. Una sonda necesita un brazo de control y un observable que el agente bajo prueba no pueda fabricar.
6. Un grep vacío es evidencia débil de ausencia, no prueba.
7. Un literal que coincide con la identidad de hoy es correcto por accidente: el invariante se deriva de la fuente que protege.
8. El nombre de un test verde es una afirmación: se audita que el cuerpo pruebe lo que el nombre promete.
9. Con `set -euo pipefail`, un pipe a `head -1` puede matar al productor con SIGPIPE y abortar el script en silencio.


FTD tampoco impone branch automático, prohibición de worktrees, el pipeline SDD completo ni `sdd-verify`: delivery, Git y aislamiento siguen la policy existente de HPL.

### Strict TDD fuera de SDD

La regla de lectura de Strict TDD tiene un único dueño, `_shared/implementation-craft.md`, que también es dueño del gate; `sdd-init`, `sdd-apply`, `sdd-verify`, `king-hpl` y `hpl-implementer` la señalan en vez de repetirla.

1. **El flag es por proyecto y lo escribe `sdd-init`** (`strict_tdd` en `openspec/config.yaml` y en `sdd/{project}/testing-capabilities` de Engram).
2. **El orden de lectura:** el marker explícito, si existe; el flag del proyecto, si `sdd-init` corrió; y si no hay nada escrito, el default por runner: con test runner, activo; sin test runner, inactivo, y se dice.
3. **Se resuelve una vez por sesión y viaja en el brief** como `Strict TDD Mode: <enabled|disabled>`: el preflight de SDD y el procedimiento FTD lo mandan en cada brief de implementación, y `king-hpl` lo resuelve en su propia sesión. En un L0 el orquestador no carga ni el preflight ni el procedimiento, así que lo resuelve el implementer con la misma regla.
4. **Un cambio sin comportamiento** —un typo en la documentación— se registra como **`N/A: no behavior changed`**, de forma honesta, y nunca como FAILED del gate.

**Qué es el marker.**

| Aspecto | Definición |
|---|---|
| Qué es | Una línea cuyo contenido entero es `Strict TDD Mode: enabled` o `Strict TDD Mode: disabled`. También vale la misma línea con el rótulo en negrita, `**Strict TDD Mode**: enabled`, que es como la escribe `sdd-init` en su reporte. Cualquier otra forma no es un marker |
| Dónde vive | En las instrucciones que el CLI anfitrión carga en la sesión, las del proyecto o las de la persona. Nunca en un archivo que escribe HPL, porque reinstalar lo reemplaza entero, y ningún archivo embarcado trae un marker suelto, así que HPL nunca activa el modo en nombre de la persona. El contenido tampoco puede nombrar el archivo de instrucciones de un CLI concreto: nombra la línea, no el archivo |
| Cómo se lee | Quien coordina la busca en las instrucciones que ya tiene en contexto, sin abrir archivos. Si hay una del proyecto y otra de la persona, gana la del proyecto; si dos se contradicen y no puede saber de dónde vino cada una, no hay marker, se pasa al flag del proyecto y se dice. `enabled` sin test runner queda inactivo, y se dice |
| Sin `sdd-init` | Funciona igual: no depende de `openspec/config.yaml` ni de Engram, y sin marker ni flag rige el default por runner |

Lo que cuesta: ningún test de la suite puede probar que un agente note la línea, sólo que la regla está escrita, que es el mismo residuo que el de los routing facts. La línea vive en archivos que HPL no escribe, así que `doctor` no la informa y la persona la escribe a mano. Una línea en las instrucciones de la persona vale para todos sus proyectos, y la del proyecto es la forma de apagarlo en uno. La procedencia de una línea no siempre está a la vista del agente, así que dos líneas contradictorias degradan al flag.

### Estrategia de tests de routing

Los tests de routing son **estáticos**, y cada uno reclama sólo lo que prueba: un test que verifica que una regla está escrita no se presenta como un test de que el modelo enruta bien.

El corpus vive en `tests/fixtures/routing-corpus/cases.json` —en una subcarpeta propia, porque `tests/fixtures/` ya tiene fixtures de otras suites— y lo prueba `tests/test_flow_routing.py`. No se instala, así que no cuesta contexto en runtime. Cada caso lleva el `request`, los cuatro `facts`, la `route`, `decided_by` —una cláusula literal de `flow-applicability.md`— y `surface`; los de transición agregan `during` (`l0` o `ftd`), el hecho nuevo que dispara la promoción y si la ruta resultante requiere aceptación explícita.

```json
{
  "request": "Subí la versión de la dependencia y arreglá lo que rompa",
  "facts": {"output_is_information": false, "asked_for_sdd": false,
            "needs_reviewable_contract": false, "needs_continuity": true},
  "route": "ftd",
  "decided_by": "<cláusula literal de flow-applicability.md>",
  "surface": "large"
}
```

| Chequeo | Qué verifica | Qué atrapa |
|---|---|---|
| Coherencia | Los `facts` de cada caso llevan a su `route` según el orden de decisión | Un caso mal etiquetado |
| Trazabilidad | `decided_by` cita una cláusula que existe literalmente en `flow-applicability.md` | Una regla borrada o renombrada que deja casos huérfanos |
| Cobertura | Cada cláusula de `flow-applicability.md` tiene al menos un caso que la cita | Una regla que nada ejercita |
| Trampas por estructura | Hay casos `surface: large` que no son SDD y casos `surface: small` que sí lo son | Que el tamaño vuelva a decidir la ruta |
| Transiciones | Los casos con `during` promueven a la ruta correcta; toda entrada a SDD por `needs_reviewable_contract` requiere aceptación; ningún caso baja desde SDD | Promociones rotas y downgrades automáticos |
| Contrato de facts | `flow-applicability.md` declara exactamente los campos que usa el corpus | Que el contrato explorer → orquestador y el corpus diverjan |

**El corpus sale de pedidos reales.** Los casos son de todas las rutas y están parafraseados y anonimizados: sin nombres de productos distintos de HPL, personas, equipos, instituciones, hosts ni correos. La procedencia de cada caso no entra al corpus. Tiene que incluir, como mínimo:

- cambios grandes que no son SDD;
- un cambio chico que sí es SDD, como dos líneas de un contrato que consumen otros;
- casos con una decisión real y sin contrato revisable, que van a FTD;
- promociones reales.

`surface` es una carnada: se anota para demostrar que no importó. Una regla de tamaño no se puede escribir en el vocabulario de los cuatro facts, así que la cobertura la rechaza: no hay caso coherente que pueda citarla.

Además del corpus: los tests de techo, con su gemelo, para `flow-applicability.md` y `king-hpl.md`; un test de lazy-load que fija que ningún cuerpo always-on incorpora el texto de `flow-applicability.md` ni de `ftd-procedure.md`, y que el procedimiento sólo se nombra en la salida de la ruta FTD de `flow-applicability.md`; y el test de punta a punta del renombre.

**Residuo declarado.** El corpus **no prueba** que el modelo, ante un pedido real, responda bien los cuatro facts, y eso queda escrito como no cubierto. Si se quiere medir, las `request` del corpus se corren a mano contra un modelo real y se comparan los facts, fuera de la suite, como los checks de release.

### Compatibilidad, permisos y seguridad

- **Wire formats**: `cli.SCHEMA`, `journal.SCHEMA`, `catalog.SCHEMA`, `journal-v4.json` y las claves y variables de entorno que enumera [Identidad de producto y raíz de composición](#identidad-de-producto-y-raíz-de-composición) no cambian por esto.
- **Quien no use FTD**: sin impacto, más allá de `docs/ftd/`, que aparece recién con el primer FTD.
- **SDD**: nada cambia adentro del ciclo. Cambia cómo se llega: por pedido explícito, o por un `needs_reviewable_contract` propuesto y aceptado.
- **Permisos**: FTD no agrega herramientas, grants MCP ni directorios. `docs/ftd/` se escribe dentro del proyecto con el `edit` y el `write` que el agente que coordina ya tiene, y ningún `may_delegate_to` cambia.
- **Controles que no se debilitan**: CBM es inteligencia de código, no evidencia de runtime; `sdd-verify` es la autoridad exclusiva de readiness SDD; ChainPR y review budget rigen SDD; se conservan `may_delegate_to`, los permisos por agente y los grants de MCP y de directorios; el journal, los snapshots, el restore y el ownership; la delivery strategy, el aislamiento y las políticas de worktree; y el techo de palabras del orquestador.

### Riesgos

| Riesgo | Mitigación |
|---|---|
| El cuerpo del orquestador crece hasta volverse el manual de todos los flujos | Techo de palabras con su gemelo contra el re-envolver, y el cómo de cada ruta en archivos que se leen sólo al recorrerla |
| `flow-applicability.md` crece hasta lo mismo | Techo propio, y el formato del record, la evidencia y el cierre viven en `ftd-procedure.md` |
| El tamaño vuelve a decidir la ruta por la puerta de atrás | Las trampas del corpus y la cobertura: una regla de tamaño no tiene caso coherente que la cite |
| Un test de routing se lee como prueba de que el modelo enruta bien | El residuo declarado, escrito en esta sección |
| FTD se vuelve ceremonia para lo que es L0 | L0 no crea record ni carga el procedimiento, y el corpus lleva casos L0 que lo fijan |
| El carril principal sale sin TDD | La regla de lectura de Strict TDD, resuelta una vez por sesión |
| *Evidence* sube al repositorio algo que no debía: los records se versionan por defecto y guardan salidas textuales | El aviso único con `.gitignore` y `.git/info/exclude`, y `ftd-procedure.md` prohíbe copiar secretos o el contenido de archivos sensibles a *Evidence* |

Los records que ya estén en `docs/ftd/` son archivos del proyecto, no de HPL: el journal no los reclama y ningún `uninstall` ni `restore` los toca.

### Fuera de alcance

Dos capacidades quedan para después, con su propio diseño y su propia aprobación:

- **Detección de brechas de skills o procedimientos.** Cuando el trabajo entregue o repita un procedimiento: si una skill o un agente ya lo cubre, se usa; si no, se registra la brecha y se **propone** una skill nueva, nunca se crea ni se instala sola. La señal es evidencia de repetición o de necesidad real, no coincidencia superficial de palabras; reutiliza el skill registry y `_shared/skill-resolver.md`, y no interrumpe un flujo activo.
- **Tooling operativo basado en evidencia.** Detectar integraciones reales del proyecto —dependencias, imports, configuraciones, variables de entorno— y sólo entonces proponer scripts, comandos o automatizaciones repetibles. Nada especulativo; nunca crear `.env` reales ni tocar credenciales; un artifact aprobado lleva como mínimo documentación, `.env.example` y un smoke test read-only; la ubicación project-local queda a evaluar.

**El pedido de "reportá una oportunidad de tooling" en cada brief queda fuera de alcance.** No es mapear: cambia lo que el orquestador escribe en cada brief y lo que cada subagente devuelve, y agrega una lista de candidatos que nadie diseñó dónde vive, todo dentro del contexto que v7 está protegiendo. La materia prima ya existe sin tocar los briefs: `hpl-verifier` devuelve *"each command as you ran it, its exit code"* (`hpl-verifier.md:42`), `hpl-implementer` devuelve *"the proof you ran and what it produced"* (`hpl-implementer.md:38-39`), *Evidence* guarda comandos textuales y Engram guarda lo que pasó entre sesiones. Para el diseño futuro quedan como punto de partida: proponer en los cierres naturales —el fin de un FTD, el cierre de una sesión— y no a mitad de trabajo; la vía a pedido por la ruta consulta (*"¿qué tools le faltan a este proyecto?"*); dónde se acumulan los candidatos y con qué umbral de repetición; y si hace falta una línea fija en el cuerpo del implementer y del verifier para lo que sólo el subagente ve.

## Memoria persistente (engram)

Engram es el servidor MCP de memoria persistente que HPL distribuye. `content/mcp/engram.md` fija una versión del build propio del fork `balerdis/engram`, con su checksum y los miembros del archivo; cada release del fork va acompañada de una release de HPL que sube ese descriptor. Las decisiones del fork viven en el fork: acá sólo está qué versión baja HPL y desde dónde. Una instalación que vincula un engram propio (`--mcp engram=<binario>`) sigue con su binario.

### Quién escribe

Un agente lanzado por otro agente no hace ninguna escritura de memoria (`mem_save`, `mem_update`, `mem_session_summary`, ni el `mem_judge` que sigue a un save) salvo que su brief se lo pida; puede seguir leyendo. Es una condición de situación, no una lista de agentes. Para las fases SDD no hace falta una regla más: el `Artifact store mode` que el orquestador inyecta en cada lanzamiento (`_shared/persistence-contract.md`) es el brief pidiendo esa escritura puntual, y ninguna fase está autorizada a guardar otra cosa.

Los `## Key Learnings` de un agente lanzado se guardan solos cuando vuelve su respuesta, una observación por ítem. Engram no guarda nada de un texto sin esa sección (`ExtractLearnings`, `PassiveCapture`), así que la captura es un opt-in y no vuelve el aluvión de escrituras no pedidas. En OpenCode la dispara `tool.execute.after` cuando la herramienta es `task` (el id llega en minúscula; también acepta `subagent`, el id de la línea 2.x, como preparación). En Claude Code la dispara el hook `SubagentStop`, que lee `last_assistant_message`. El bloque compartido `system-prompt/mcp/engram.md` le dice al agente que habla con la persona que no hace falta guardarlos de nuevo ni buscar en memoria para confirmarlo. Ese bloque también pide escribir cada memoria, título y contenido, en prosa normal con espacio entre palabras, porque la búsqueda de texto completo de engram compara palabras enteras y una memoria con palabras pegadas no aparece al buscar una de ellas.

El plugin de OpenCode no inyecta ningún protocolo de memoria: el único protocolo es el bloque ambient, que viaja sólo cuando se elige engram.

### Claude Code: hooks propios

Sólo cuando el servidor engram está elegido, HPL agrega tres entradas a `~/.claude/settings.json`, como `append` con huella (`uninstall` y `restore` sacan exactamente esas tres y los hooks del usuario no se tocan), y escribe `<data_dir>/hooks/engram-hook.py`, un script de biblioteca estándar:

- `SessionStart` (`startup|resume|clear|fork`, síncrono) arranca `engram serve` con el binario que administra HPL si no contesta (con un engram vinculado usa el `engram` del PATH) y registra la sesión.
- `UserPromptSubmit` (asíncrono) registra el prompt: más de 10 caracteres, etiquetas privadas fuera, credenciales tapadas con el catálogo de transporte de credenciales y recorte a 2000 caracteres, tapando antes de recortar.
- `SubagentStop` (asíncrono) manda `last_assistant_message`, si pasa de 50 caracteres, a la captura pasiva.

Garantías: la salida estándar siempre queda vacía, el hook siempre termina en `0` y no hace nada dentro de un sub-agente. El comando va envuelto como `command -v python3 ... && python3 ... || true`. Las llamadas locales a engram ignoran el proxy HTTP del entorno, y por encima del tope de detección de 256 KiB el hook falla cerrado. No hay `Stop` ni `SessionEnd`, ni recordatorios periódicos, ni protocolo inyectado: escribe en memoria sólo quien habla con la persona, y sólo cuando pasó algo durable.

HPL no instala el plugin de Claude Code del fork de engram: registraría un segundo servidor MCP con otros nombres de herramienta, salteando las reglas por herramienta y la versión fijada; depende del PATH, de `jq` y de `curl`; queda fuera del journal; y no se podría renombrar para otra distribución.

### El puerto por usuario

`engram serve` elige un puerto por usuario. El plugin de OpenCode (`engram.ts`), el hook (`engram-hook.py`) y `doctor` (`core/engram_port.py`) aplican la misma regla:

1. Si `ENGRAM_PORT` trae un puerto válido, se usa ese. Si lo tiene **sólo otro uid**, no se manda nada, no se arranca `engram serve` y no se prueba otro puerto: la persona lo eligió a propósito.
2. Si no, se usa 7437 cuando nadie lo escucha o cuando el propio uid está entre los que lo escuchan.
3. Si 7437 lo tiene sólo otro uid, se usa `17437 + (uid % 10000)`, con la misma regla: libre o propio, se usa; de otro, no se manda nada. Es derivado, no reservado: dos uids que difieren en 10000 comparten número, y si choca falla cerrado.
4. Sin `/proc/net/tcp` no se puede saber, y se usa el puerto explícito o 7437.

Quién escucha se lee de `/proc/net/tcp` y `/proc/net/tcp6` (sockets en LISTEN y la columna del uid), en `core/listeners.py`; el hook es un script estándar y el plugin es TypeScript, así que cada uno lleva su copia chica, estricta por igual (sólo dígitos y largo acotado en `ENGRAM_PORT` y en el uid; hexadecimal acotado en el puerto). `tests/test_engram_port_parity.py` corre vectores compartidos (`tests/fixtures/engram_port_vectors.json`) contra las tres implementaciones.

La decisión se recalcula antes de cada petición, porque una decisión guardada se vuelve obsoleta justo en el sentido peligroso; el servidor propio se arranca con `ENGRAM_PORT=<puerto>` explícito en el entorno del hijo, y tras arrancarlo se vuelve a mirar quién escucha antes de la primera escritura. `doctor` agrega un aviso opcional que no bloquea (`engram_port_warning`, y una línea `Warning:`) para una CLI donde HPL instaló el plugin o el hook: dice qué uid ocupa el puerto y qué va a hacer HPL. El servidor MCP de engram (stdio) abre SQLite directo y no usa el puerto.

Límites: sólo Linux; `/proc` muestra el namespace de red actual, así que dentro de un contenedor no se ven los puertos de afuera; se sabe de quién es el socket, no qué programa es; entre mirar y escribir queda una ventana mínima que la segunda mirada achica, no elimina. Un `engram serve` que siga corriendo de una versión anterior contesta con el comportamiento viejo hasta que se lo detiene.

### Qué binario usa el plugin de OpenCode

Al instalar un engram descargado para OpenCode, `render.mcp` escribe `plugins/engram-bin.json` con `{"engram_bin": <ruta>}`, la misma ruta que lleva la clave del MCP. Es un artefacto más del journal. El plugin resuelve el binario en este orden: `ENGRAM_BIN` del entorno, la ruta gestionada si existe y es ejecutable, `engram` del PATH y, por último, el nombre `engram`. Así el plugin, el MCP y el hook usan la misma versión.

## Transporte de credenciales

Una credencial que la persona pega en un mensaje es suya para administrar: se usa para la tarea y nunca se aconseja rotarla. El diseño tiene cuatro decisiones:

1. **Detección automática por contexto, sin marcador.** Nunca por "parece aleatorio": un hash, un checksum, un UUID o un número pelado no se marcan, porque se pegan todo el tiempo y tienen que sobrevivir. Se detecta un valor junto a un nombre de clave sensible, un header de autenticación, una contraseña en una URL o un formato de token conocido. Un valor se reemplaza por una variable `$HPL_SECRET_<NOMBRE>`.
2. **Los valores viven sólo en memoria**, durante la vida del proceso de OpenCode, compartidos por todas sus sesiones. Nada se escribe a disco; al reiniciar se pierden.
3. **No hay filtro de salida en vivo.** Un comando que imprime el valor mientras corre lo deja en el historial y en la TUI; el modelo nunca lo ve. Se mitiga con una regla de contenido: nunca imprimir una variable de credencial.
4. **Split hexagonal.** El núcleo lleva las reglas de contenido (`## Credential Transport` en `system-prompt/AGENTS.md`) y el catálogo de detección como dato (`content/security/credential-transport-catalog.json`, esquema `hpl/credential-transport-catalog/v1`). El puerto es una capacidad del adapter con cuatro operaciones: detectar y reemplazar en la entrada, inyectar en la ejecución, redactar en la salida y redactar antes de escribir a memoria (`CredentialTransportCapability`, `core/credential_transport.py`). Un adapter que no la implementa declara las cuatro en `False`.

En OpenCode la implementa el plugin `secret-transport.ts`, con una copia verbatim del catálogo escrita a su lado; `chat.message` reemplaza los valores antes de que se persistan, `shell.env` los inyecta y `tool.execute.after` redacta la salida. `engram.ts` llama a la misma función antes de postear prompts y capturas. Claude Code no la implementa: `UserPromptSubmit` no puede reescribir el prompt, así que el modelo ve lo que se escribe y sólo la copia guardada en engram está cubierta.

Detalles del catálogo:

- Junto a una clave sensible alcanzan 4 caracteres (`key_context.min_value_length`); fuera de ese contexto se exigen 8. Una lista cerrada de valores de relleno (`null`, `true`, `changeme`, `placeholder`…) no se marca.
- Un header se marca por el sufijo de su nombre (`-Signature`, `-Token`, `-Key`, `-Secret`, con un segmento numérico final opcional, como `X-Hub-Signature-256`).
- El valor sin comillas se corta en `;`, `&`, `?` y `:`, para no tragarse el resto de una query string y para que el escaneo sea lineal. Por encima de `max_detect_bytes` (256 KiB) se saltean los pasos de detección y sólo se redactan los valores ya registrados.
- Un valor sin comillas que es puro texto de identificador, sin ningún dígito, no se detecta en el paso `clave=valor`: es un hueco aceptado.
- Cuando el mensaje trae una variable `$HPL_SECRET_<NOMBRE>` que este proceso no tiene registrada, el plugin lo avisa; la nota de valores reemplazados nunca se duplica y, cuando aplican las dos cosas, es un solo bloque. Todo falla abierto: un error en este camino nunca bloquea el mensaje.

Una credencial que llega tal cual escrita no fue reemplazada: se usa como viene, se mantiene fuera de commits, de escrituras de memoria y de cualquier archivo que no sea un archivo sensible donde la persona pidió guardarla, y no se repite en una respuesta.

## Archivos sensibles

La regla `## Sensitive Files` de `system-prompt/AGENTS.md` obliga a todo agente: no se lee, imprime, edita, copia, versiona ni expone un archivo sensible sin permiso de la persona para ese archivo, y una tarea general o una shell elevada no son ese permiso. Cuando el propio mensaje de la persona pide guardar credenciales en un archivo sensible que nombra, ese pedido es el permiso para ese archivo: un archivo regular de estilo `.env`, nombrado exactamente, nunca un symlink ni algo bajo `.ssh/`, `.aws/credentials`, `*.pem` o `*.key` desde la shell. La carga a un comando silencia los errores y no se corre nada cuya salida pueda repetir un valor. Con permiso, el agente abre el archivo con su herramienta de lectura o edición y no con la shell, para que se aplique la confirmación propia de la CLI; es una guía para el modelo, no un cumplimiento. El texto está fijado por tests (`tests/test_sensitive_files_rule.py`).

Por debajo del prompt hay un piso que lo hace cumplir donde el runtime lo permite:

- **OpenCode.** `read` y `edit` (`edit` también gobierna `write` y `apply_patch`) se renderizan como `{"*": "allow", <piso>}`. Un agente `mode: primary` recibe `"ask"`; uno `mode: subagent`, `"deny"`, porque un `ask` a profundidad de delegación dos o mayor se cuelga (#39112). El runtime pasa `path.relative(worktree, archivo)` como patrón, así que cada entrada tiene además una forma `*/` que atrapa rutas fuera del proyecto. El piso cubre `.env`, `.env.*`, `*.env`, `*.env.*` (para no ser más débil que el default del propio runtime), `.ssh/`, `.credentials/`, `secrets/`, `.aws/credentials`, `.config/gh/hosts.yml`, `*.pem` y `*.key`, sin excepción para `.env.example`.
- **Claude Code.** `permissions.ask` lleva reglas `Read` y `Edit` sobre las formas `//**/` de las entradas de archivo; las de directorio están en `permissions.deny`, y `deny` gana a `ask`. Los permisos allí son por sesión, así que los sub-agentes también reciben la pregunta; en una sesión sin cabeza, un `ask` actúa como rechazo.

El `ask` del piso cubre las herramientas de archivos, no comandos de shell como `cat .env`; sólo una regla `deny` llega al shell, y sólo en Claude Code. Sigue sin cubrirse `bash` de OpenCode sobre archivos sensibles, `grep` y `glob` (su patrón es de búsqueda, no una ruta), los symlinks y los alias. Es un piso contra el descuido, no una frontera contra un agente que busca evitarlo.

### Directorios externos en Claude Code

Claude Code recibe la misma decisión que OpenCode: los directorios externos al worktree están permitidos por default, con el mismo piso de denegación. `content.DENY_FLOOR_DIRECTORIES` (`core/content.py`) es la única lista, en forma agnóstica (`.ssh`, `.aws`, `.credentials`, `secrets`, `.config/gh`); el adapter de OpenCode la traduce a comodines `*/<dir>/*` y el de Claude Code a `PERMISSIONS_DENY_FLOOR`. `render.permission_artifacts` (`adapters/claudecode/render.py`) devuelve doce artefactos, uno por regla: dos para `PERMISSIONS_ALLOW` (`Read(//**)`, `Edit(//**)`; `Edit` alcanza también a `Write`, y una regla `Write(path)` nunca se consulta, por eso HPL no escribe ninguna) y diez para el piso (`Read(//**/<dir>/**)` y `Edit(//**/<dir>/**)` por cada directorio, que bloquean también un `cat` de Bash sobre esas rutas). Cada uno es un `ConfigKeyArtifact` con puntero terminado en `/-`, identificado por su huella, así que las entradas de la persona sobreviven a instalar, actualizar y desinstalar. `permissions.additionalDirectories` no se escribe nunca (sólo concede lectura) ni se fija `defaultMode`.

El reporte de `directory grant` y `revoke` lo arma `DirectoryGrantBehavior` (`allowed_by_default`, `writes_own_entry`), que declara cada adapter: el CLI nunca compara un id de adapter, y por eso dice la verdad en cada CLI (en las dos un directorio otorgado no cambia nada observable salvo que solape el piso).

## Guardia de push de los sub-agentes

Un `git push` de un sub-agente pide confirmación en las dos CLIs; el coordinador, el agente primario, no cambia donde la CLI lo permite. Un bloqueo total se descartó porque a veces la persona le pide a un agente que suba.

- **OpenCode.** Todo agente `mode: subagent` con `bash` recibe un mapa de patrones: `"*": "allow"` y después `git push` más los `gh` que escriben hacia afuera (`pr create`, `pr merge`, `issue create`, `release create`, `repo create`), cada uno en su forma simple, con prefijo de entorno (`FOO=1 git push`) y con ruta absoluta del binario (`SUBAGENT_BASH_PERMISSION` en `adapters/opencode/render.py`). La forma con prefijo de entorno coincide con cualquier `=` antes del texto del comando y sólo dispara si más adelante aparece ` git push` o ` gh <escritor>`: es un sobre-aviso conocido y aceptado.
- **Claude Code.** Sus permisos son por sesión: el frontmatter de un agente sólo concede o quita herramientas, nunca «pregunta». Las reglas se agregan a `permissions.ask` de `settings.json` como `append`; la confirmación alcanza también al coordinador.

Sigue sin atraparse: alias, scripts propios, un push dentro de `sh -c` o `eval`, los `gh` con banderas globales antes del subcomando, `gh api -X POST` y `gh pr comment`. Los patrones con comodín preguntan además por cualquier git cuyos argumentos contengan «push» (los commits se protegen con `commit -F`, y `git log --grep push` sigue preguntando de más), de modo que «nunca hacer push» sigue siendo además una instrucción.

## Entrega en paralelo

`skills/_shared/parallel-delivery.md` es el procedimiento del orquestador cuando un fan-out tiene escritores. Se carga sólo desde dos punteros: el del cuerpo del orquestador y el de «Writers in parallel» de `sub-delegation-criterion.md`; ningún otro cuerpo siempre cargado lo nombra. El patrón: clasificar el trabajo pendiente, repartirlo por propiedad de archivos, un worktree por escritor, lanzar todo en un mensaje, integrar con `cherry-pick`, correr la suite integrada, revisar con contexto limpio, un único escritor de arreglos y cierre a cargo del coordinador. Es genérico: no trae los nombres de ningún proyecto.

Decisiones:

1. **Los escritores commitean en local.** Cada unidad que escribe hace UN commit local en la rama de su worktree, nunca hace push y no lleva atribución de IA ni de herramienta. El coordinador integra con `git cherry-pick` y comprueba con `git cherry <rama de integración> <rama>` que cada commit entró (sólo en picks limpios) antes de retirar el worktree y la rama. Ante un conflicto entre unidades disjuntas la partición estaba mal: se hace `git cherry-pick --abort`, se para y se avisa.
2. **El coordinador corre la suite integrada**, una sola vez sobre el árbol integrado: un solo comando, la salida redirigida a un archivo, y comprobar que la cuenta de tests cierra. Es la excepción a «ejecutar pruebas: delegar».
3. **Los worktrees viven fuera del repositorio, igual en las dos CLIs.** Los crea el coordinador con `git worktree add -b <rama> <ruta> <base>`, sin apoyarse en el aislamiento propio de ninguna CLI, que puede ponerlos dentro del repo. La ruta es `${XDG_STATE_HOME:-$HOME/.local/state}/agent-worktrees/<repo>-<hash corto del toplevel>/<run-id>/<unidad>`.
4. **Avance por unidad** cuando la CLI entrega los resultados de a uno, y sólo el consolidado cuando llegan todos juntos.

Ningún comando del procedimiento contiene `$(...)` ni `${...}` y ninguno encadena `cd` con una redirección, porque un sistema de permisos sólo puede juzgar un comando que puede leer: cada valor se calcula en su propio comando simple y se usa `git -C <ruta absoluta>`. Un conflicto dice si la partición estaba mal o si `main` se movió, y nombra cada ruta restante; el brief lleva el comando de pruebas con rutas absolutas; hay un paso de recuperación para una corrida interrumpida.

Lo que se leyó de las CLIs: en OpenCode 1.18.x varias llamadas `task` en un mensaje corren concurrentes, `task` no tiene parámetro de directorio ni de aislamiento y el modo en segundo plano es experimental; en Claude Code varias llamadas `Agent` corren concurrentes y `isolation: "worktree"` pone el worktree dentro del repo, así que el procedimiento emula lo mismo en las dos: el coordinador crea el worktree y cada escritor trabaja con rutas absolutas. Se ejercitó en vivo en Claude Code y en OpenCode. Las diez incertidumbres concretas tienen su fila en las deudas sin unidad asignada.

## Aviso de lo que una CLI carga de otra

`CliAdapter.foreign_loads()` declara lo que una CLI lee de otra (por ejemplo, OpenCode carga instrucciones y skills de Claude Code) y devuelve `ForeignLoad`; el núcleo lo evalúa y redacta sin comparar ids de adapter, y `doctor` e `install`/`update` usan el mismo texto. Sólo hay existencia y conteos; ningún archivo se abre. Las variables que lo apagan se leen como las lee OpenCode: `true`/`yes`/`on`/`1`/`y` son verdaderos, `false`/`no`/`off`/`0`/`n` falsos, mayúsculas distinguidas, y cualquier otro valor seteado es un error de configuración que el aviso dice; un valor vacío se trata como no seteado. El conteo de skills es acotado: el puerto de filesystem no resuelve rutas reales, así que un symlink de directorio se sigue sólo si cuelga directo de la raíz de skills y sólo cuentan los archivos regulares llamados `SKILL.md`; puede contar de menos respecto del glob de OpenCode.

## Dependencias fijadas y mantenimiento

- Cada servidor MCP descargable fija versión e integridad en su descriptor (`content/mcp/*.md`). `tools/check_dependency_updates.py` lista las versiones más nuevas de cada dependencia fijada (releases de GitHub para cbm y engram, npm para playwright); no cruza la versión mayor, marca para revisión manual toda 0.x más nueva, sólo informa salvo con `--strict`, y se corre antes de cada release.
- `update` borra las versiones viejas de los servidores descargados que nadie usa: después de un install o update exitoso, y en `uninstall`, borra los directorios `<data_dir>/mcp/<nombre>/<versión>` fuera del conjunto a conservar (todo destino registrado por cualquier instalación del journal, las versiones fijadas y el destino previo de esta CLI, para que un `hpl restore` siga andando). Sólo se tocan hijos directos de nombres que HPL administra, nunca se sigue un symlink, el borrado es de mejor esfuerzo y se informa en `pruned_dependencies`. Restaurar una generación más vieja que un update pide un `hpl update` después, porque `restore` nunca descarga.
- `install.sh` instala OpenCode 1.19.5 cuando no se pide otra versión con `--opencode-version`; no reinstala un OpenCode presente y `hpl update` no lo toca.
- Si la información de releases no se puede leer, no hay traceback: el aviso del menú calla y no reintenta durante una hora; `hpl upgrade` termina con código 1 y un mensaje corto según el motivo (404, 401 o 403, límite de consultas, otro estado HTTP, falla de red, respuesta que no es una descripción de release, o falla del checksum o del binario) sin reemplazar nada. `DownloaderError` lleva `status` y `rate_limited`, y `core.upgrade.describe_download_failure` los traduce.

## Evidencia de Strict TDD entre tandas de apply

Bajo Strict TDD, la tabla de evidencia de cada tanda de `sdd-apply` es un registro propio, escrito una vez y nunca reescrito: en engram con `topic_key` `sdd/{change-name}/apply-evidence/{n}`, en openspec como un archivo nuevo `apply-evidence-{n}`. `apply-progress` lleva un libro (`## TDD Evidence Ledger`) con una línea por tanda: la clave del registro, las tareas que cubre y la fecha; en cada merge se copian las líneas existentes y se agrega la nueva. Una tarea reabierta recibe filas nuevas en el registro de la tanda que la reabre. `sdd-verify` recupera cada registro del libro y juzga cada tarea con todas sus filas; un registro que no se puede recuperar es CRITICAL («evidence record unavailable»). La razón: mientras la evidencia viva dentro del artefacto que se reescribe, depende de que cada tanda no la toque, y un modelo ante una reescritura larga comprime igual. `tests/test_tdd_evidence_ledger.py` fija la clave, la regla de escribir una vez, la copia del libro y la lectura en verify.

## La TUI y los reportes por CLI

- **Ajuste de línea.** `view.py` (que nunca toca una terminal) decide dónde parte una línea de prosa más ancha que la ventana, en vez de recortarla; `app.draw()` sólo dibuja lo que recibe. No se ajusta la fila de un menú o de una lista de elección (una `Line` por ítem, porque el scroll y el cursor cuentan filas), ni el wordmark ni la barra de progreso.
- **Una feature por-CLI se nombra como tal.** De los miembros de `Capability` sólo `PER_AGENT_MODEL` difiere entre los adapters registrados (OpenCode sí, Claude Code no) y tiene superficie propia (`hpl models`, `Configure models`). El motivo de una capacidad ausente lo declara el adapter (`CapabilityManifest.reasons` y `reason_for`), un manifest rechaza un motivo para una capacidad que declara `True`, y la CLI, la TUI y la ayuda de `hpl models` lo muestran con la misma voz; la fila de una CLI sin la capacidad se marca como deshabilitada con su motivo en vez de fallar al entrar.

## Deudas sin unidad asignada

Trabajo conocido que se acarrea a propósito. Cada ítem declara qué lo destraba, para que el acarreo sea una decisión y no un olvido, y qué puede hacer una persona mientras siga abierto —vacío donde no hay nada útil que decir—. Acá va sólo lo que todavía está por decidirse o por hacerse: lo que funciona así a propósito vive en [Limitaciones aceptadas](#limitaciones-aceptadas), más abajo.

| Deuda | Qué la destraba | Qué hacer mientras tanto |
|-------|-----------------|--------------------------|

| Un agente recibe `apply_patch` sin que HPL se la conceda nunca, y esto no tiene arreglo de código: el pliegue está verificado en dos lugares independientes del runtime, no uno. `packages/opencode/src/permission/index.ts` (`const edits = ["edit", "write", "apply_patch"]`) agrupa los tres bajo el permiso `edit` al decidir qué herramientas manda, y el comodín del mapa `tools` no lo alcanza porque ese filtro compara por clave exacta. Por separado, `packages/core/src/v1/config/agent.ts` (`normalize`) chequea el permiso declarado contra el literal `"patch"`, no `"apply_patch"` — así que `tools: { apply_patch: false }` no es un intento fallido, es un no-op silencioso: genera una clave `permission.apply_patch` que el runtime nunca consulta. Ningún hook de plugin puede sacar una herramienta de la lista de las que se mandan al modelo — se verificó leyendo la interfaz completa de hooks. Y aguas arriba ya se decidió no separarlo: el issue #40150 pedía esto mismo para `write` y se cerró con el PR #47352, que es sólo documentación y dice que el hilo convergió en que es un problema de documentación y no de código; el #18008 lo pedía para agentes de plan específicamente y se cerró sin fix. Así que todo agente al que este producto le concede `edit` o `write` recibe la herramienta y su descripción imperativa, «Use the `apply_patch` tool to edit files». La afirmación es la regla y no el conteo, que se lleva solo: hoy son **14 agentes**, y la cifra no se retipea acá sino que se deriva del árbol de contenido —los agentes cuyo mapa de herramientas renderizado enciende `edit` o `write`— en `ApplyPatchReachesEveryEditingAgentTest` (`tests/test_architecture_debt_figures.py`), que falla el día que deja de coincidir. Un número escrito en palabras no tendría nada que lo comparara con nada, y quedaría falso en silencio cuando se embarque un agente más. No es escalada: escribe exactamente lo que `edit` ya permite. Lo que rompía era la lectura del render, que presentaba `"*": false` como si cerrara todo lo no nombrado. Ya costó una confusión real: un agente trató esa descripción como instrucción de mayor prioridad que el prompt de sistema y se negó a editar por SSH | **La salida es documental, y la corrección viaja además por el canal de la propia herramienta.** Los docstrings de `_tools` y `_permission` en `render.py` declaran el pliegue, explican por qué añadir `apply_patch` a `TOOL_NAME` o `PERMISSION_NAME` sería ese mismo no-op, y un guardián (`ApplyPatchPermissionFoldTest` en `tests/test_opencode_adapter.py`) fija que ninguna de las dos tablas nombra `apply_patch`, con mutación probada en ambas. La mitigación más fuerte, sin embargo, no es documental: el producto embarca `src/hpl/adapters/opencode/assets/plugins/apply-patch-scope.ts`, que engancha `tool.definition` y le agrega un párrafo de alcance a la descripción de la propia herramienta, así que la corrección llega por el mismo canal que la frase que se leyó mal. Tenía que llegar por ahí: el texto que viaja con las definiciones de herramientas pesa más que el que viaja como prompt, y una negativa real mostró que dos intentos del lado del prompt no alcanzaban a corregirla. Enmienda una descripción; no saca una herramienta, así que lo que dice la columna de al lado sobre los hooks sigue entero. Su motivo y su límite están en el archivo y en «Enmendar el texto del runtime, no sólo agregar el propio»; acá sólo se lo nombra, y `ApplyPatchScopeIsCorrectedOnTheToolChannelTest` (`tests/test_architecture_debt_figures.py`) deriva del árbol cuál es el plugin que escribe esa descripción y exige que la fila lo nombre. La otra salida —pedirle al runtime que evalúe `apply_patch` por su propio nombre— no depende de este código: depende de que los mantenedores de OpenCode reabran una decisión que ya tomaron dos veces. Nada de esto cierra la deuda: la herramienta le sigue llegando a todo agente que pueda editar, y lo único que cambia es que ya no puede leerse mal desde adentro del producto | Si un agente cita la descripción de `apply_patch` para negarse a editar, decírselo en el pedido: el prompt compartido ya la nombra y no hay forma de sacarle la herramienta sin sacarle `edit` y `write` con ella. Y no leer el `"*": false` del render como si cerrara lo que no nombra — ya no hace falta inferirlo, el propio `render.py` lo dice |
| En un cliente ACP —Zed y similares— el `ask` de un sub-agente podría no llegar nunca a una persona y dejar la llamada colgada en vez de fallar limpio. El handler busca la sesión en un registro que sólo contiene las que creó el propio ciclo ACP, y la sesión hija que lanza la herramienta `task` no está ahí, así que retorna sin contestar ni allow ni reject: el `Deferred` queda pendiente sin timeout hasta que se destruya la instancia | Poder ejecutar OpenCode bajo un cliente ACP, que es lo único que lo confirma o lo descarta. Es análisis de fuente, no observación: quien lo leyó no pudo descartar que otro camino registre la sesión hija antes de que corra el handler. Mientras tanto queda dicho en la documentación, que es lo honesto al no poder probar todos los clientes | Bajo un cliente ACP, una llamada de sub-agente que queda colgada sin haber preguntado nada no se libera sola: hay que cortar la sesión. Bajo la TUI de OpenCode el camino no se recorre |
| No hay CI en el repositorio: `.github/` no existe, y la verificación del catálogo generado la corre la suite y no un servicio | Nada técnico. Se decidió no incorporar CI por ahora, por lento y molesto. Lo que ocupa su lugar son dos prácticas que se cumplen en cada cambio: toda modificación corre la suite completa antes de darse por terminada, y todo trabajo pasa por una revisión adversarial en contexto fresco cuya única consigna es romperlo. La segunda es la que más rinde y la que menos respaldo tiene: los defectos más caros los encuentra esa revisión y no la suite, por eso `docs/release-distribution.md` abre con los dos pasos y con el motivo por el que el segundo no es opcional | Antes de publicar, correr la suite completa a mano y seguir el procedimiento de `docs/release-distribution.md` |
| El orquestador delega de más, hasta cosas chicas que no lo justifican. Reportado por el usuario a partir de uso real, no de una lectura de código. Una de sus causas posibles, la viñeta del umbral que manda a delegar toda ejecución de pruebas, tiene una excepción nombrada (la corrida única de la suite completa sobre el árbol integrado la hace el coordinador), y la entrega en paralelo no se ofrece para trabajo chico | Que el usuario junte casos reales y los pase, para poder mirar qué texto los produce. La sospecha es un texto que empuja a un modelo literal a delegar —la misma clase de causa que una inundación de escrituras de memoria no pedidas— pero no hay todavía un caso concreto para confirmarlo | Nada por ahora |
| Entrega en paralelo medida sólo en parte. Diez riesgos (el procedimiento sigue siendo largo, y eso es una preocupación abierta): (1) en OpenCode, una llamada `edit`/`write` con ruta relativa se resuelve contra el checkout principal, no contra el worktree; (2) en OpenCode, los patrones del permiso `edit` son relativos al proyecto y un archivo externo produce `../..`, así que un permiso por ruta relativa no coincidiría (los riesgos (1) y (2) no se observaron en las corridas en vivo en OpenCode: la verificación de aislamiento pasó; siguen abiertos porque no se midieron de forma adversaria); (3) en Claude Code, un hijo en segundo plano recibe un conjunto reducido de herramientas, sin MCP; (4) en Claude Code, no se midió si un `cd` de Bash a un directorio externo pide permiso; (5) el procedimiento se ejercitó en vivo en Claude Code `-p` y en OpenCode, y se midieron en vivo con Claude Code el conflicto de cherry-pick y la corrida interrumpida; sigue sin observarse el camino de una unidad lanzada que falla; (6) **resuelto en parte** (en OpenCode, un subagente de profundidad dos o mayor que dispare el `ask` queda esperando un aviso que ninguna vista muestra, #39112; a profundidad uno el aviso aparece en la sesión raíz según el código fuente, sin medir): un `git push` de un subagente pide confirmación en las dos CLIs (ver «Guardia de push de los sub-agentes»), y lo que sigue sin atraparse son alias, scripts propios, `sh -c`/`eval`, los `gh` con banderas globales antes del subcomando, `gh api -X POST` y `gh pr comment`, y los patrones con comodín preguntan también por cualquier git cuyos argumentos contengan «push» (los commits se protegen con `commit -F`, y `git log --grep push` pregunta de más), de modo que «nunca hacer push» sigue siendo además una instrucción; `FOO=1 git push` y la ruta absoluta al binario sí se cubren; en Claude Code la confirmación también alcanza al coordinador; (7) en Claude Code HPL no renderiza ninguna regla de allow de Bash, de modo que cada comando de git y de pruebas del procedimiento cae al aviso por defecto salvo que la configuración propia de la persona lo permita, y un `cd <dir> && git ...` se deniega (por eso el procedimiento usa `git -C` y nunca encadena `cd` con git); un `cd <dir> && <comando> > <archivo>` se deniega siempre, porque Claude Code no puede saber contra qué directorio se resuelve el destino de la redirección tras un `cd` en un compuesto, y `--add-dir` no lo arregla (por eso el procedimiento nunca encadena `cd` con una redirección); (8) el modo fork interactivo de Claude Code vuelve a todo hijo un hijo en segundo plano, sin medir con este procedimiento; (9) el default propio del runtime para el trailer de commit puede agregar atribución, y lo que lo atrapa es la verificación del paso 12; (10) alcance: el orquestador llega al procedimiento por el puntero del cuerpo siempre cargado y no por el criterio; medido en Claude Code `-p` y en OpenCode | Correr una entrega real de dos unidades en cada CLI, con una ruta relativa de prueba, un `cd` externo y un hijo que pida una herramienta MCP, y mirar `git status --porcelain` del checkout principal | Las instrucciones del brief (ruta absoluta, comandos dentro del worktree, sin push) y la verificación de aislamiento del paso 7 son la única defensa; si el estado del checkout principal muestra algo que escribió una unidad, parar y avisar |
| OpenCode 2 (`@opencode/cli`) **no está soportado, en espera** por decisión de la persona. Sale aparte de `opencode-ai`, sin notas de release publicadas (#52184); el issue del propio equipo «V2 beta: isolate storage/database from stable OpenCode data» (#34831) sigue abierto, todos los canales resuelven a `opencode.db` y v2 le aplica sus migraciones; hubo regresiones entre parches (#52259, #52284); su binario también se llama `opencode`, así que tapa al 1.x en el PATH. Lo que rompería hoy en HPL, leído del código y no corrido: los plugins necesitan un export por defecto `{id, setup}`; `instructions` no se resuelve, así que `hpl-AGENTS.md` quedaría inerte; MCP en modo Code Mode es el default y HPL deniega `execute`; cambió la forma de la salida de la herramienta de sub-agentes, que pasa a llamarse `subagent` (el disparador de captura pasiva ya acepta ese id); `subagent_depth` pasa a `experimental.subagent_depth`, con default 1; y `apply_patch` pasa a ser `patch`. Su hook `shell` / `create.before` ya existe, así que el transporte de credenciales no espera un hook | Retomar cuando ocurra cualquiera de estas: `opencode-ai` latest pasa a 2.x o la release «Latest» de GitHub es v2; se cierra #34831; aparecen notas de release de v2. Hay que volver a verificar el mapa de lo que rompe | Nada |
| Quien tenga a la vez los hooks de engram de HPL en Claude Code y el plugin de engram del fork guarda cada prompt dos veces: una con las credenciales tapadas (el hook de HPL) y otra tal como se escribió (el `UserPromptSubmit` del plugin, que solo saca `<private>`) | Tapar credenciales también en el plugin, o que HPL detecte el plugin instalado y lo avise | No tener los dos a la vez: con HPL en Claude Code, desinstalar el plugin de engram |
| Recuperación después de compactar bajo Claude Code: los hooks no cubren `compact` ni devuelven contexto a la sesión | Decidir qué se devuelve y cómo sin volver a un protocolo inyectado de memoria | Pedirle al agente `mem_context` al retomar |
| El hook de engram de Claude Code no tiene el equivalente de `redactKnownValues` del plugin de OpenCode: tapa por catálogo, pero no los valores que la sesión ya conoce | Portar el mecanismo al script del hook | No pegar credenciales en prompts, que bajo Claude Code el modelo igual las ve |

---

## Limitaciones aceptadas

Acá no hay nada pendiente, y esa es la razón de separarla de la tabla de arriba. Una deuda declara qué la destraba porque se espera que alguna vez se destrabe; una limitación describe cómo funciona el producto a propósito, con el motivo por el que se eligió así. Mezclarlas en una sola tabla promete en silencio un arreglo para lo que no va a arreglarse. Una fila se muda de acá para arriba sólo si la decisión se reabre.

| Limitación | Por qué es así | Qué hacer al respecto |
|------------|----------------|-----------------------|
| La TUI no expone `directory grant` ni `revoke`, mientras sí expone `mcp grant`. La invariante del proyecto va en una sola dirección —toda acción de la TUI tiene comando equivalente— así que nada falla, pero es una asimetría con `mcp grant` | Conceder un directorio es una acción rara y deliberada, del tipo que uno tipea una vez; atar un servidor MCP se hace durante una instalación guiada, que es donde la TUI gana de verdad. La invariante va en una sola dirección —toda acción de la TUI tiene comando equivalente, no al revés—, así que la asimetría no rompe nada, y la paridad inversa no se buscó porque no compra nada. Esta fila es ese porqué puesto por escrito | Conceder un directorio se tipea una vez con `hpl directory grant` y se saca con `hpl directory revoke`; la TUI no hace falta para eso |
| El plugin de Zellij usa `hpl-zellij-state` como nombre de directorio en `~/.config/` y `~/.cache/`, y ahí la marca del motor se queda. El archivo del plugin sí se deriva, así que una distribución termina con un `<producto>-zellij-state.ts` escribiendo en un `~/.config/hpl-zellij-state/`: una asimetría deliberada, no un olvido | Derivar esos dos nombres es de una línea: el problema no es el código sino el estado que ya está adentro. Esos directorios viven fuera del directorio de configuración del CLI, el journal no los reclama y ningún retiro los alcanza, así que derivarlos huerfanizaría en silencio lo que la persona ya tiene y la instalación arrancaría con estado limpio sin decírselo. Se decidió sostener la asimetría hasta que haya una migración explícita que mueva el directorio, y el motivo quedó escrito adentro del propio `.ts` para que nadie lo «arregle» sin verlo | Nada: el directorio se llama así aunque la distribución tenga otro nombre, y renombrarlo a mano deja al plugin sin encontrar su propio estado |
| Una edición a mano sobre un artefacto que HPL instaló no sobrevive: el próximo `install` o `update` la reescribe con la versión del release, y `uninstall` la borra, sin preguntar en ninguno de los dos casos. Vale igual para una clave de configuración que HPL posee dentro de `opencode.json` | La huella no es permiso: pertenecer al journal alcanza para actualizar y para retirar (`_file_step` y `retire`, `src/hpl/core/planner.py`). Lo que protege una edición es el snapshot previo a escribir, no una negativa a escribir — separar «recuperar» de «pisar» es lo que evita que una edición ajena congele para siempre una dirección que el producto necesita poder mover | No hace falta saberlo de antes: el propio aviso de `install` y `update` nombra `hpl restore` y cuántas generaciones se retienen, derivado de la constante. Recuperarla con `hpl restore [generación]`, que devuelve los bytes y el modo exactos previos al comando, con **20 generaciones** de retención y no más (`RETAIN_GENERATIONS`, `src/hpl/cli.py`). Antes de aplicar, `--dry-run` adelanta qué se va a pisar. Para que un cambio propio dure: no se hace sobre un archivo de HPL — se construye una distribución propia, o se guarda una copia fuera del directorio de configuración del CLI |
| Un item agregado a una lista —un `append`— queda afuera del aviso `overwritten`, así que una edición tuya sobre uno de esos se pisa sin que nada lo cuente | Se lo localiza por huella, no por dirección: si el valor difiere, no se encuentra, y «alguien editó el nuestro» es indistinguible de «alguien borró el nuestro y agregó el suyo». Avisar sobre lo segundo sería inventar un conflicto donde no lo hay | Nada lo detecta de antemano. El snapshot lo cubre igual: `hpl restore` devuelve el archivo entero como estaba antes del comando |
| `uninstall` no tiene aviso equivalente al `overwritten` de `install` y `update`: borra cada dirección reclamada e informa el id que sacó, sin decir si el contenido que había ahí era el del release o uno tuyo | `install` tiene que leer cada dirección para decidir si hace falta escribirla, así que la comparación contra la huella le sale gratis. `uninstall` no necesita leer nada para borrar, y leerlo todo sólo para poder avisar sería trabajo agregado para una advertencia que llega cuando ya decidiste desinstalar | `hpl restore` inmediatamente después, que devuelve el estado exacto anterior al `uninstall` — verificado ejecutándolo, con la edición a mano incluida. El propio reporte del `uninstall` lo nombra, con su límite de generaciones, en vez de dejar la promesa sólo en el manual. Si hay algo propio conviviendo con artefactos de HPL, copiarlo afuera antes |
| `render._permission` renderiza `external_directory` con línea de base `"*": "allow"` para todo agente y toda profundidad, sin preguntar por ningún acceso fuera del árbol del proyecto. La expone —no la motiva— un bug abierto de OpenCode: en `packages/tui/src/routes/session/index.tsx`, la vista que lista permisos pendientes sólo mira un nivel de sesión (`children()` filtra por `parentID === session().id`, y `permissions()` devuelve `[]` apenas `session()?.parentID` existe), así que el `ask` de un sub-agente a profundidad ≥ 2 nunca aparece en ninguna pantalla y la llamada de herramienta se cuelga para siempre, sin límite de tiempo — issues `anomalyco/opencode#39112` (abierto), `#43996` (abierto), `#44747` (abierto), y `#30635` (cerrado arreglando sólo un nivel). HPL embarca `subagent_depth: 10`, así que esa profundidad es habitual, no una rareza: se reprodujo en vivo con `hpl-orchestrator` → `hpl-general` → `hpl-explorer`. El costo es real y se acepta a sabiendas: la línea de base deja de preguntar también en profundidad 0 y 1, donde sí preguntaba bien, y `hpl directory grant` queda dormido para una ruta ordinaria, no inútil — su propia entrada sigue en el journal y se sigue renderizando igual, y recuperaría su sentido completo sin que haga falta volver a otorgarla si la línea de base volviera a `"ask"`. Lo único que sigue denegado en su grafía canónica es un piso fijo y chico (`.ssh/`, `.aws/`, `.credentials/`, `.config/gh/`, `secrets/`), escrito después de cualquier concesión para que gane bajo la resolución `findLast` del runtime — necesariamente por directorio, nunca por archivo, porque el runtime sólo pregunta por `dirname(destino) + "/*"`, nunca por el archivo mismo. Ese piso hay que leerlo por lo que es y no por lo que suena: el match es sobre el string literal, sin `realpath` en ningún lado, así que es un guardia contra quien entra por accidente, no una frontera contra quien entra a propósito — un symlink, un bind mount, o una variable como `GH_CONFIG_DIR`/`AWS_SHARED_CREDENTIALS_FILE` lo atraviesan sin tocarlo, y un agente con `bash` bajo esta misma línea de base `allow` puede construir esa vuelta él mismo. Y todo lo que el piso no alcanza por construcción — un `*.pem`, un `*.key`, un `.env` que viva fuera de esos cinco directorios, que es casi cualquier otro lugar — queda alcanzable de verdad, no sólo "sin guardia en abstracto" | Habilitar `external_directory` por default es una decisión de producto, tomada con el costo de la columna anterior a la vista: en el uso cotidiano, tener eso habilitado es una ventaja. El bug abierto de OpenCode (`#39112` y las hermanas `#43996`/`#44747`) no la motiva, sólo la expuso: hizo visible en vivo cuánto costaba la alternativa —un `ask` a profundidad que se cuelga para siempre en vez de preguntar o fallar— frente a esa ventaja de uso cotidiano. Si esos issues se resuelven río arriba, eso no revierte por sí solo esta línea de base en `_permission` (`src/hpl/adapters/opencode/render.py`): la decisión tendría que reabrirse pesando de nuevo la ventaja contra el costo, no darse vuelta sola porque el bug que la expuso ya no está. El piso de denegación (`EXTERNAL_DIRECTORY_DENY_FLOOR`) es una decisión aparte: nada en ésta, ni un arreglo upstream, obliga a sacarlo | Un directorio otorgado con `hpl directory grant` no cambia nada observable salvo que solapara uno de los cinco directorios siempre denegados, en cuyo caso sigue denegado igual — pero no lo revoques por eso: sigue guardado por si la línea de base volviera a `"ask"`. Nadie debe asumir que un permiso de `external_directory` sirve de gate contra un agente decidido — no lo es, para ningún agente, a ninguna profundidad, ni siquiera dentro de los cinco directorios del piso |
| `ProcedureIsLazyTest` es léxico: impide que un cuerpo que se carga siempre nombre `ftd-procedure.md` o su frase distintiva, pero no ve un cuerpo que parafrasee su contenido con otras palabras. Hoy ninguno lo hace | Un chequeo de texto no reconoce una paráfrasis, y no hay arreglo barato que lo haga: reconocerla es juzgar el significado, que es trabajo de una revisión y no de un test. Un corpus de sinónimos tampoco alcanza, porque parafrasear un procedimiento no es cambiar una palabra por otra. Lo mecánico sí está cubierto —el nombre del archivo, su frase distintiva y el único puntero, a la salida de la ruta FTD—. Nada la destraba | Al revisar un cambio a un cuerpo que se carga siempre —cada agente, sus secciones MCP y el prompt de sistema—, mirar a mano que no repita el procedimiento FTD con otras palabras |


## Verificación de la arquitectura

Tests que fallan si el diseño se degrada:

- [ ] Ningún módulo fuera de `adapters/` menciona el id de un CLI
- [ ] El registry rechaza un adapter con manifiesto incoherente
- [ ] El catálogo commiteado coincide con el generado desde el contenido
- [ ] Cada acción de la TUI tiene comando equivalente
- [ ] Cada capacidad declarada en `True` tiene ruta y render
- [ ] Cada códec serializa de forma canónica y preserva las claves que HPL no escribió
- [ ] El journal rechaza targets fuera del home del usuario
- [ ] Instalar y desinstalar escriben lo que el journal reclama sin consultar la huella del artefacto
- [ ] Toda instalación y toda desinstalación toma un snapshot antes de escribir
- [ ] `restore` devuelve bytes y modo exactos, sin merge ni reconstrucción
- [ ] Desinstalar deja el sistema sin rastros de HPL, incluido lo que el usuario modificó sobre una dirección propia; lo único que puede quedar es un ítem de lista que no se pudo identificar
- [ ] La retención acota la historia de snapshots, y una limpieza que falla no vuelve fallido el comando que ya escribió
- [ ] Instalar retira lo que el journal reclama y el render ya no produce, y el snapshot cubre esas direcciones
- [ ] El journal descarta lo que el retiro confirmó haber removido, nunca lo que se pretendía remover

---
## Cómo se sostiene este documento

Lo que dice este documento se verifica contra el árbol: las cifras que podrían envejecer sin que nadie lo note se derivan del contenido y se comprueban en la suite (`tests/test_architecture_debt_figures.py`, `tests/test_docs_footer_literals.py`, `tests/test_external_directory_deny_floor_docs.py`), y `tools/check_docs_links.py` falla ante un enlace roto. Lo que no se puede verificar así —una medición en vivo, una lectura del código de un runtime— está dicho como tal, con el límite de lo que se observó.
