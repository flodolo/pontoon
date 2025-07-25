from django.db import models

from pontoon.base.models import Priority, Project, Resource


class TagQuerySet(models.QuerySet):
    def serialize(self):
        return [tag.serialize() for tag in self]


class Tag(models.Model):
    slug = models.CharField(max_length=20)
    name = models.CharField(max_length=30)
    project = models.ForeignKey(
        Project, models.CASCADE, blank=True, null=True, related_name="tags"
    )
    resources = models.ManyToManyField(Resource)
    priority = models.IntegerField(blank=True, null=True, choices=Priority.choices)

    objects = TagQuerySet.as_manager()

    class Meta:
        unique_together = [["slug", "project"]]

    def serialize(self):
        return {
            "slug": self.slug,
            "name": self.name,
            "priority": self.priority,
        }
