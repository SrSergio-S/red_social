# Modelo de datos

Base de datos relacional (SQLite por defecto) definida con SQLAlchemy en [`app/models.py`](../app/models.py).
GitHub dibuja automáticamente el siguiente diagrama entidad-relación:

```mermaid
erDiagram
    USUARIOS ||--o{ SEGUIMIENTOS : "sigue"
    MATERIAS ||--o{ SEGUIMIENTOS : "es seguida"
    USUARIOS ||--o{ APUNTES : "publica"
    MATERIAS ||--o{ APUNTES : "contiene"
    APUNTES ||--o{ APUNTE_ETIQUETAS : ""
    ETIQUETAS ||--o{ APUNTE_ETIQUETAS : ""
    USUARIOS ||--o{ CALIFICACIONES : "califica"
    APUNTES ||--o{ CALIFICACIONES : "recibe"
    USUARIOS ||--o{ LIKES : "da like"
    APUNTES ||--o{ LIKES : "recibe"
    USUARIOS ||--o{ DESCARGAS : "descarga"
    APUNTES ||--o{ DESCARGAS : "es descargado"
    USUARIOS ||--o{ COMENTARIOS : "escribe"
    APUNTES ||--o{ COMENTARIOS : "foro del apunte"
    MATERIAS ||--o{ COMENTARIOS : "foro de la materia"
    COMENTARIOS ||--o{ COMENTARIOS : "respuestas"
    USUARIOS ||--o{ SOLICITUDES_TUTORIA : "solicita"
    USUARIOS ||--o{ SOLICITUDES_TUTORIA : "es tutor"
    MATERIAS |o--o{ SOLICITUDES_TUTORIA : "sobre"
    APUNTES |o--o{ SOLICITUDES_TUTORIA : "referencia"

    USUARIOS {
        int id PK
        string nombre
        string email UK
        string password_hash
        string carrera
        int semestre
        text bio
        bool ofrece_tutorias
        bool es_admin
        datetime fecha_registro
    }
    MATERIAS {
        int id PK
        string codigo UK
        string nombre
        text descripcion
        string carrera
        int semestre
    }
    SEGUIMIENTOS {
        int usuario_id PK,FK
        int materia_id PK,FK
        datetime fecha
    }
    APUNTES {
        int id PK
        string titulo
        text descripcion
        string tipo
        string nombre_original
        string nombre_almacenado UK
        string extension
        string mimetype
        int tamano_bytes
        string hash_sha256
        datetime fecha_subida
        int autor_id FK
        int materia_id FK
    }
    ETIQUETAS {
        int id PK
        string nombre UK
    }
    APUNTE_ETIQUETAS {
        int apunte_id PK,FK
        int etiqueta_id PK,FK
    }
    CALIFICACIONES {
        int id PK
        int usuario_id FK
        int apunte_id FK
        int estrellas "CHECK 1..5"
        datetime fecha
    }
    LIKES {
        int usuario_id PK,FK
        int apunte_id PK,FK
        datetime fecha
    }
    DESCARGAS {
        int id PK
        int usuario_id FK
        int apunte_id FK
        datetime fecha
    }
    COMENTARIOS {
        int id PK
        text contenido
        datetime fecha
        int autor_id FK
        int apunte_id FK "nulo si es de materia"
        int materia_id FK "nulo si es de apunte"
        int padre_id FK "respuesta a"
    }
    SOLICITUDES_TUTORIA {
        int id PK
        int solicitante_id FK
        int tutor_id FK
        int materia_id FK
        int apunte_id FK
        string tema
        text mensaje
        string modalidad
        datetime fecha_propuesta
        string estado
        text respuesta_tutor
    }
```

## Relaciones muchos a muchos

| Relación | Tabla intermedia | Datos extra en la relación |
|---|---|---|
| Un estudiante sigue muchas materias / una materia tiene muchos estudiantes | `seguimientos` | fecha en que empezó a seguirla |
| Un estudiante da "me gusta" a muchos apuntes / un apunte gusta a muchos | `likes` | fecha |
| Un estudiante califica muchos apuntes / un apunte recibe muchas calificaciones | `calificaciones` (modelo propio) | estrellas 1–5, fecha |
| Un estudiante descarga muchos apuntes / un apunte es descargado por muchos | `descargas` (modelo propio) | fecha (historial) |
| Un apunte tiene muchas etiquetas / una etiqueta está en muchos apuntes | `apunte_etiquetas` | — |

## Reglas de integridad en la base de datos

- **`UNIQUE (usuario_id, apunte_id)`** en `calificaciones`: un estudiante solo puede calificar una vez cada apunte (si vuelve a calificar, se actualiza).
- **`CHECK (estrellas BETWEEN 1 AND 5)`** en `calificaciones`.
- **`CHECK`** en `comentarios`: cada comentario pertenece a un apunte **o** a una materia, nunca a ambos ni a ninguno.
- **`ON DELETE CASCADE`**: al borrar un apunte se borran sus calificaciones, likes, descargas y comentarios (en SQLite se activa con `PRAGMA foreign_keys=ON`, ver `app/__init__.py`).
- La clave primaria compuesta de `seguimientos` y `likes` impide seguir dos veces la misma materia o dar dos likes al mismo apunte.

## Metadatos de archivos

El archivo físico se guarda en `instance/uploads/` con un nombre aleatorio (UUID) para evitar choques y
nombres peligrosos. En la tabla `apuntes` se almacena: nombre original, nombre almacenado, extensión,
tipo MIME, tamaño en bytes y hash **SHA-256** del contenido (sirve para detectar archivos duplicados).

## Estados de una tutoría

```mermaid
stateDiagram-v2
    [*] --> pendiente : el estudiante solicita
    pendiente --> aceptada : el tutor acepta
    pendiente --> rechazada : el tutor rechaza
    pendiente --> cancelada : el estudiante cancela
    aceptada --> completada : el tutor la marca como hecha
    aceptada --> cancelada : el estudiante cancela
```

## Consultas SQL de ejemplo

```sql
-- Promedio de estrellas y número de descargas por apunte
SELECT a.titulo,
       ROUND(AVG(c.estrellas), 1)              AS promedio,
       (SELECT COUNT(*) FROM descargas d WHERE d.apunte_id = a.id) AS descargas
FROM apuntes a
LEFT JOIN calificaciones c ON c.apunte_id = a.id
GROUP BY a.id
ORDER BY promedio DESC;

-- Materias con más seguidores
SELECT m.nombre, COUNT(s.usuario_id) AS seguidores
FROM materias m
LEFT JOIN seguimientos s ON s.materia_id = m.id
GROUP BY m.id
ORDER BY seguidores DESC;

-- Estudiantes que siguen "Bases de Datos"
SELECT u.nombre
FROM usuarios u
JOIN seguimientos s ON s.usuario_id = u.id
JOIN materias m ON m.id = s.materia_id
WHERE m.codigo = 'SIS305';
```
