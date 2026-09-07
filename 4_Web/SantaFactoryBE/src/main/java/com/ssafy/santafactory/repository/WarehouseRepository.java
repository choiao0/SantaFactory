package com.ssafy.santafactory.repository;

import com.ssafy.santafactory.entity.warehouse.Warehouse;
import org.springframework.data.jpa.repository.JpaRepository;

public interface WarehouseRepository extends JpaRepository<Warehouse, Long> {
}
