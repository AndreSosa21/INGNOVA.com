"""Modelo de datos del MVP (SQLAlchemy 2). Funciona igual en PostgreSQL (Supabase) y SQLite.

Dos grupos de tablas:
  * Operación y entrenamiento: catálogos, proveedores, flota, conductores, tarifas,
    disponibilidad, solicitudes, servicios históricos, imprevistos y evaluación COSCO.
  * Memoria del asistente LLM: decisiones tomadas y casos/lecciones aprendidas.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------- catálogos
class Region(Base):
    __tablename__ = "regiones"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(60), unique=True)


class Ciudad(Base):
    __tablename__ = "ciudades"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(60), unique=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("regiones.id"))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    es_puerto: Mapped[bool] = mapped_column(Boolean, default=False)
    factor_terreno: Mapped[float] = mapped_column(Float, comment=">1 = vía más lenta")
    riesgo_vial: Mapped[float] = mapped_column(Float, comment="prob. base de imprevisto")


class TipoVehiculo(Base):
    __tablename__ = "tipos_vehiculo"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(60), unique=True)
    capacidad_t: Mapped[float] = mapped_column(Float)
    teu: Mapped[int] = mapped_column(Integer, comment="contenedores TEU que transporta")
    mult_tarifa: Mapped[float] = mapped_column(Float)
    velocidad_kmh: Mapped[float] = mapped_column(Float)


class TipoCarga(Base):
    __tablename__ = "tipos_carga"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(60), unique=True)
    certificacion_requerida: Mapped[str | None] = mapped_column(String(60))
    sensibilidad: Mapped[float] = mapped_column(Float, comment="prob. de daño si hay imprevisto")


class CompatibilidadCarga(Base):
    __tablename__ = "compatibilidad_carga"
    tipo_carga_id: Mapped[int] = mapped_column(ForeignKey("tipos_carga.id"), primary_key=True)
    tipo_vehiculo_id: Mapped[int] = mapped_column(ForeignKey("tipos_vehiculo.id"), primary_key=True)
    preferencia: Mapped[int] = mapped_column(Integer, comment="1 = vehículo preferido")


class Cliente(Base):
    __tablename__ = "clientes"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120))
    sector: Mapped[str] = mapped_column(String(60))
    ciudad_id: Mapped[int] = mapped_column(ForeignKey("ciudades.id"))


# ---------------------------------------------------------------- proveedores
class Proveedor(Base):
    __tablename__ = "proveedores"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), unique=True)
    nit: Mapped[str] = mapped_column(String(20))
    ciudad_base_id: Mapped[int] = mapped_column(ForeignKey("ciudades.id"))
    anio_fundacion: Mapped[int] = mapped_column(Integer)
    fecha_inicio_cosco: Mapped[date] = mapped_column(Date, comment="desde cuándo trabaja con COSCO")
    tiempo_reaccion_prom_h: Mapped[float] = mapped_column(Float, comment="declarado por el proveedor")
    puntaje_desempeno_cosco: Mapped[float] = mapped_column(Float, comment="0-100, últimos 6 meses")
    otd_historico: Mapped[float] = mapped_column(Float, comment="entregas a tiempo, todo el historial")
    tiempo_entrega_prom_h: Mapped[float] = mapped_column(Float)
    servicios_historicos: Mapped[int] = mapped_column(Integer)
    contacto: Mapped[str] = mapped_column(String(120))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)

    cobertura: Mapped[list["Cobertura"]] = relationship(back_populates="proveedor")


class Certificacion(Base):
    __tablename__ = "certificaciones"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(60), unique=True)


class ProveedorCertificacion(Base):
    __tablename__ = "proveedor_certificaciones"
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"), primary_key=True)
    certificacion_id: Mapped[int] = mapped_column(ForeignKey("certificaciones.id"), primary_key=True)
    vence: Mapped[date] = mapped_column(Date)


class Cobertura(Base):
    __tablename__ = "cobertura"
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"), primary_key=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("regiones.id"), primary_key=True)
    proveedor: Mapped[Proveedor] = relationship(back_populates="cobertura")


class Vehiculo(Base):
    __tablename__ = "vehiculos"
    id: Mapped[int] = mapped_column(primary_key=True)
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"), index=True)
    tipo_vehiculo_id: Mapped[int] = mapped_column(ForeignKey("tipos_vehiculo.id"), index=True)
    placa: Mapped[str] = mapped_column(String(10), unique=True)
    modelo_anio: Mapped[int] = mapped_column(Integer)
    estado: Mapped[str] = mapped_column(String(20), comment="Excelente/Bueno/Regular/Malo")
    puntaje_estado: Mapped[float] = mapped_column(Float, comment="0-100 según inspección")
    kilometraje: Mapped[int] = mapped_column(Integer)
    gps: Mapped[bool] = mapped_column(Boolean)
    ultima_revision: Mapped[date] = mapped_column(Date)


class Conductor(Base):
    __tablename__ = "conductores"
    id: Mapped[int] = mapped_column(primary_key=True)
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"), index=True)
    nombre: Mapped[str] = mapped_column(String(120))
    cedula: Mapped[str] = mapped_column(String(15))
    anios_experiencia: Mapped[int] = mapped_column(Integer)
    # métricas COSCO 0-100
    puntualidad: Mapped[float] = mapped_column(Float)
    seguridad_vial: Mapped[float] = mapped_column(Float)
    documentacion: Mapped[float] = mapped_column(Float)
    cuidado_carga: Mapped[float] = mapped_column(Float)
    comunicacion: Mapped[float] = mapped_column(Float)
    puntaje_total: Mapped[float] = mapped_column(Float)


class Tarifa(Base):
    __tablename__ = "tarifas"
    id: Mapped[int] = mapped_column(primary_key=True)
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"), index=True)
    tipo_vehiculo_id: Mapped[int] = mapped_column(ForeignKey("tipos_vehiculo.id"))
    tarifa_km_cop: Mapped[float] = mapped_column(Float)
    cargo_fijo_cop: Mapped[float] = mapped_column(Float, comment="cargue, descargue, peajes base")
    vigente_desde: Mapped[date] = mapped_column(Date)
    __table_args__ = (UniqueConstraint("proveedor_id", "tipo_vehiculo_id", "vigente_desde"),)


class Disponibilidad(Base):
    __tablename__ = "disponibilidad"
    id: Mapped[int] = mapped_column(primary_key=True)
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"), index=True)
    tipo_vehiculo_id: Mapped[int] = mapped_column(ForeignKey("tipos_vehiculo.id"))
    fecha: Mapped[date] = mapped_column(Date, index=True)
    vehiculos_totales: Mapped[int] = mapped_column(Integer)
    vehiculos_disponibles: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("proveedor_id", "tipo_vehiculo_id", "fecha"),)


# ---------------------------------------------------------------- operación histórica
class Solicitud(Base):
    __tablename__ = "solicitudes"
    id: Mapped[int] = mapped_column(primary_key=True)
    fecha_solicitud: Mapped[datetime] = mapped_column(DateTime, index=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"))
    origen_id: Mapped[int] = mapped_column(ForeignKey("ciudades.id"))
    destino_id: Mapped[int] = mapped_column(ForeignKey("ciudades.id"))
    tipo_carga_id: Mapped[int] = mapped_column(ForeignKey("tipos_carga.id"))
    tipo_vehiculo_id: Mapped[int] = mapped_column(ForeignKey("tipos_vehiculo.id"))
    unidades: Mapped[int] = mapped_column(Integer, comment="contenedores o viajes")
    peso_t: Mapped[float] = mapped_column(Float)
    plazo_horas: Mapped[float] = mapped_column(Float, comment="tiempo acordado con el cliente")
    presupuesto_cop: Mapped[float | None] = mapped_column(Float)
    prioridad: Mapped[str] = mapped_column(String(20), comment="Equilibrado/Tiempo/Costo/Carga crítica")
    fase: Mapped[str] = mapped_column(String(12), comment="historico / prueba")
    estado: Mapped[str] = mapped_column(String(20), comment="atendida / pendiente")


class Servicio(Base):
    """Un viaje ejecutado por un proveedor para una solicitud (una solicitud puede tener varios)."""

    __tablename__ = "servicios"
    id: Mapped[int] = mapped_column(primary_key=True)
    solicitud_id: Mapped[int] = mapped_column(ForeignKey("solicitudes.id"), index=True)
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"), index=True)
    vehiculo_id: Mapped[int] = mapped_column(ForeignKey("vehiculos.id"))
    conductor_id: Mapped[int] = mapped_column(ForeignKey("conductores.id"))
    fecha_cargue: Mapped[datetime] = mapped_column(DateTime, index=True)
    distancia_km: Mapped[float] = mapped_column(Float)
    unidades: Mapped[int] = mapped_column(Integer)
    tiempo_planeado_h: Mapped[float] = mapped_column(Float)
    tiempo_real_h: Mapped[float] = mapped_column(Float)
    a_tiempo: Mapped[bool] = mapped_column(Boolean)
    costo_cotizado_cop: Mapped[float] = mapped_column(Float)
    costo_final_cop: Mapped[float] = mapped_column(Float)
    tuvo_imprevisto: Mapped[bool] = mapped_column(Boolean)
    dano_carga: Mapped[bool] = mapped_column(Boolean)
    calificacion_cliente: Mapped[int] = mapped_column(Integer, comment="1-5")


class Imprevisto(Base):
    __tablename__ = "imprevistos"
    id: Mapped[int] = mapped_column(primary_key=True)
    servicio_id: Mapped[int] = mapped_column(ForeignKey("servicios.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(40))
    tiempo_reaccion_h: Mapped[float] = mapped_column(Float, comment="hasta que el proveedor actúa")
    retraso_h: Mapped[float] = mapped_column(Float)
    costo_extra_cop: Mapped[float] = mapped_column(Float)
    descripcion: Mapped[str] = mapped_column(Text)


class EvaluacionMensual(Base):
    """Estándar de desempeño COSCO por proveedor y mes (0-100 por métrica)."""

    __tablename__ = "evaluaciones_mensuales"
    id: Mapped[int] = mapped_column(primary_key=True)
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"), index=True)
    mes: Mapped[date] = mapped_column(Date)
    servicios: Mapped[int] = mapped_column(Integer)
    otd: Mapped[float] = mapped_column(Float)
    siniestralidad: Mapped[float] = mapped_column(Float, comment="100 = sin siniestros")
    documentacion: Mapped[float] = mapped_column(Float)
    comunicacion_trazabilidad: Mapped[float] = mapped_column(Float)
    cumplimiento_tarifa: Mapped[float] = mapped_column(Float)
    puntaje_total: Mapped[float] = mapped_column(Float)
    __table_args__ = (UniqueConstraint("proveedor_id", "mes"),)


# ---------------------------------------------------------------- memoria del asistente
class Decision(Base):
    """Lo que recomendó el sistema y lo que eligió la persona de operaciones (alimenta al bandido)."""

    __tablename__ = "decisiones"
    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[datetime] = mapped_column(DateTime)
    solicitud_id: Mapped[int] = mapped_column(ForeignKey("solicitudes.id"))
    proveedor_recomendado_id: Mapped[int | None] = mapped_column(ForeignKey("proveedores.id"))
    proveedor_elegido_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"))
    exito_predicho: Mapped[float | None] = mapped_column(Float, comment="% de éxito Monte Carlo")
    motivo: Mapped[str | None] = mapped_column(Text)
    usuario: Mapped[str | None] = mapped_column(String(60))
    resultado_a_tiempo: Mapped[bool | None] = mapped_column(Boolean, comment="se llena al cerrar el servicio")
    resultado_costo_cop: Mapped[float | None] = mapped_column(Float)


class CasoMemoria(Base):
    """Casos y lecciones que el asistente recuerda ("en un caso parecido pasó X y causó Y")."""

    __tablename__ = "casos_memoria"
    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[datetime] = mapped_column(DateTime)
    origen_id: Mapped[int | None] = mapped_column(ForeignKey("ciudades.id"))
    destino_id: Mapped[int | None] = mapped_column(ForeignKey("ciudades.id"))
    tipo_carga_id: Mapped[int | None] = mapped_column(ForeignKey("tipos_carga.id"))
    proveedor_id: Mapped[int | None] = mapped_column(ForeignKey("proveedores.id"))
    servicio_id: Mapped[int | None] = mapped_column(ForeignKey("servicios.id"))
    titulo: Mapped[str] = mapped_column(String(200))
    que_paso: Mapped[str] = mapped_column(Text)
    consecuencia: Mapped[str] = mapped_column(Text)
    leccion: Mapped[str] = mapped_column(Text)
    importancia: Mapped[int] = mapped_column(Integer, comment="1-5")
    etiquetas: Mapped[str] = mapped_column(String(200), comment="separadas por coma")
    fuente: Mapped[str] = mapped_column(String(20), comment="historico / usuario / asistente")


# ---------------------------------------------------------------- motor de decisión
class RequisitoSolicitud(Base):
    """Restricciones y preferencias de COSCO para una solicitud (p. ej. "llegar en 36 h" o "priorizar tiempo").

    Una restricción descarta a quien no la cumpla; una preferencia solo cambia los pesos del puntaje.
    """

    __tablename__ = "requisitos_solicitud"
    id: Mapped[int] = mapped_column(primary_key=True)
    solicitud_id: Mapped[int] = mapped_column(ForeignKey("solicitudes.id"), index=True)
    factor: Mapped[str] = mapped_column(String(30), comment="precio / tiempo / confiabilidad / certificacion / proveedor ...")
    tipo: Mapped[str] = mapped_column(String(12), comment="restriccion / preferencia")
    valor: Mapped[str | None] = mapped_column(String(120), comment="límite o valor, p. ej. 36 (h) o 'excluir:5'")
    confirmado_por: Mapped[str | None] = mapped_column(String(60), comment="persona que lo confirmó")
    fecha: Mapped[datetime] = mapped_column(DateTime)


class ConversacionAgente(Base):
    """Lo que la persona escribió al asistente y los campos que el LLM extrajo, antes y después de confirmar."""

    __tablename__ = "conversaciones_agente"
    id: Mapped[int] = mapped_column(primary_key=True)
    solicitud_id: Mapped[int | None] = mapped_column(ForeignKey("solicitudes.id"), index=True)
    fecha: Mapped[datetime] = mapped_column(DateTime)
    texto_original: Mapped[str] = mapped_column(Text)
    campos_extraidos: Mapped[dict | None] = mapped_column(JSON, comment="JSON con origen, destino, carga, plazo, ...")
    confirmado_por: Mapped[str | None] = mapped_column(String(60))


class EstadoBandit(Base):
    """Parámetros Beta(alfa, beta) del bandido por proveedor y segmento (región destino × tipo de carga)."""

    __tablename__ = "estado_bandit"
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"), primary_key=True)
    segmento: Mapped[str] = mapped_column(String(80), primary_key=True, comment="'<region_id>|<tipo_carga_id>' o 'global'")
    alfa: Mapped[float] = mapped_column(Float)
    beta: Mapped[float] = mapped_column(Float)
    actualizado: Mapped[datetime] = mapped_column(DateTime)


class SolicitudPortal(Base):
    """Datos que el cliente escribió en el portal: quién pide y cuándo llegó. La solicitud en sí vive en `solicitudes`."""

    __tablename__ = "solicitudes_portal"
    solicitud_id: Mapped[int] = mapped_column(ForeignKey("solicitudes.id"), primary_key=True)
    creada: Mapped[datetime] = mapped_column(DateTime, index=True)
    contacto: Mapped[str] = mapped_column(String(120))
    empresa: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(120))
    notas: Mapped[str | None] = mapped_column(Text)
