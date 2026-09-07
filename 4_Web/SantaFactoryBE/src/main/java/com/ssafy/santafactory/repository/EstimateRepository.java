package com.ssafy.santafactory.repository;

import com.ssafy.santafactory.entity.estimate.Estimate;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

public interface EstimateRepository extends JpaRepository<Estimate, Long> {

    /** 견적 목록 — 최근순 (명세 §3-1 GET /estimates). */
    Page<Estimate> findAllByOrderByCreatedAtDesc(Pageable pageable);
}
