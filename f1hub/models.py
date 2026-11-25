from django.db import models

# Estados compartidos por el modelo de trabajos, f1hub.jobs y la plantilla de
# telemetría (los valores son los que consume el sondeo JSON).
STATUS_PENDING = "pending"
STATUS_GENERATING = "generating"
STATUS_READY = "ready"
STATUS_ERROR = "error"
TELEMETRY_JOB_STATUS_CHOICES = [
    (STATUS_PENDING, "Pendiente"),
    (STATUS_GENERATING, "Generando"),
    (STATUS_READY, "Listo"),
    (STATUS_ERROR, "Error"),
]


class Season(models.Model):
    year = models.IntegerField(unique=True)
    regulations = models.TextField(help_text="Technical regulations description")

    def __str__(self):
        return f"{self.year} Season"

class Event(models.Model):
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name='events')
    name = models.CharField(max_length=200)
    location = models.CharField(max_length=200)
    date = models.DateField()
    round_number = models.IntegerField()

    class Meta:
        ordering = ['date']
        unique_together = ('season', 'round_number')

    def __str__(self):
        return f"Round {self.round_number}: {self.name} ({self.season.year})"

class Session(models.Model):
    SESSION_TYPES = [
        ('FP1', 'Free Practice 1'),
        ('FP2', 'Free Practice 2'),
        ('FP3', 'Free Practice 3'),
        ('Qualifying', 'Qualifying'),
        ('Sprint Shootout', 'Sprint Shootout'),
        ('Sprint', 'Sprint'),
        ('Race', 'Race'),
    ]
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Completed', 'Completed'),
    ]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='sessions')
    name = models.CharField(max_length=50, choices=SESSION_TYPES)
    date_time = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')

    class Meta:
        ordering = ['date_time']

    def __str__(self):
        return f"{self.event.name} - {self.name}"

class Driver(models.Model):
    name = models.CharField(max_length=100)
    acronym = models.CharField(max_length=3, unique=True)
    team = models.CharField(max_length=100)
    nationality = models.CharField(max_length=50)
    # Puede ser nulo en datos antiguos: la vista solo rechaza pilotos cuyo
    # año asignado difiere del de la sesión seleccionada.
    season = models.ForeignKey(
        Season,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="drivers",
    )

    def __str__(self):
        return f"{self.name} ({self.acronym})"

class TelemetryCache(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name='telemetry_caches')
    driver1 = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name='telemetry_driver1')
    driver2 = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name='telemetry_driver2')
    file_path = models.CharField(max_length=500, help_text="Local path to the generated plot or data file")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # El servicio normaliza la pareja por acronym; la BD garantiza que no
        # existan dos filas para la misma sesión y pareja canónica.
        unique_together = ("session", "driver1", "driver2")

    def __str__(self):
        return f"Telemetry: {self.driver1.acronym} vs {self.driver2.acronym} - {self.session}"


class TelemetryJob(models.Model):
    """Estado persistente de la generación asíncrona de un gráfico.

    A diferencia del registro en memoria anterior, la fila vive en la BD: el
    endpoint de sondeo la lee desde cualquier worker y el trabajo sobrevive a
    reinicios del servidor. La clave es la canónica del servicio (temporada +
    sesión + pareja ordenada), así que ``VER vs COL`` y ``COL vs VER``
    comparten una única fila.
    """

    key = models.CharField(max_length=200, unique=True)
    session = models.ForeignKey(
        Session, on_delete=models.CASCADE, related_name="telemetry_jobs"
    )
    driver1 = models.ForeignKey(
        Driver, on_delete=models.CASCADE, related_name="telemetry_jobs_driver1"
    )
    driver2 = models.ForeignKey(
        Driver, on_delete=models.CASCADE, related_name="telemetry_jobs_driver2"
    )
    status = models.CharField(
        max_length=20, choices=TELEMETRY_JOB_STATUS_CHOICES, default=STATUS_PENDING
    )
    plot_path = models.CharField(max_length=500, blank=True, default="")
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"TelemetryJob {self.key} ({self.status})"


class DriverStanding(models.Model):
    """Posición final de un piloto en el campeonato (datos de Ergast/Jolpica)."""

    season_year = models.IntegerField()
    position = models.IntegerField()
    points = models.FloatField()
    wins = models.IntegerField()
    driver_code = models.CharField(max_length=10)
    driver_name = models.CharField(max_length=200)
    constructor_name = models.CharField(max_length=200)

    class Meta:
        ordering = ["position"]
        unique_together = ("season_year", "driver_code")

    def __str__(self):
        return f"{self.position}. {self.driver_name} ({self.driver_code}) - {self.season_year}"


class ConstructorStanding(models.Model):
    """Posición final de un equipo en el campeonato (datos de Ergast/Jolpica)."""

    season_year = models.IntegerField()
    position = models.IntegerField()
    points = models.FloatField()
    wins = models.IntegerField()
    constructor_name = models.CharField(max_length=200)

    class Meta:
        ordering = ["position"]
        unique_together = ("season_year", "constructor_name")

    def __str__(self):
        return f"{self.position}. {self.constructor_name} - {self.season_year}"
