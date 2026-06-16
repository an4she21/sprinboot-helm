-- Script SQL pour créer la base de données springboot
-- Exécutez ce script dans HeidiSQL ou via la ligne de commande MySQL/MariaDB

CREATE DATABASE IF NOT EXISTS springboot;
USE springboot;

-- Les tables seront créées automatiquement par Hibernate au démarrage de l'application
-- grâce à la configuration spring.jpa.hibernate.ddl-auto=update
