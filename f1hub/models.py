from django.db import models

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

    def __str__(self):
        return f"{self.name} ({self.acronym})"

class TelemetryCache(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name='telemetry_caches')
    driver1 = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name='telemetry_driver1')
    driver2 = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name='telemetry_driver2')
    file_path = models.CharField(max_length=500, help_text="Local path to the generated plot or data file")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Telemetry: {self.driver1.acronym} vs {self.driver2.acronym} - {self.session}"
